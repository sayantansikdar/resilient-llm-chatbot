import asyncio
import logging
import time
import weakref
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import Settings
from .db import ChatStore
from .llm import AllProvidersUnavailable, LLMGateway, build_key_pool
from .schemas import ChatMetadata, ChatRequest, ChatResponse, HealthResponse, HistoryResponse
from .simulation import InvalidSimulationHeader, parse_simulation_header

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("chat.api")

# LiteLLM's own logging is chatty and can echo request payloads
logging.getLogger("LiteLLM").setLevel(logging.WARNING)


class SessionLocks:
    """One lock per session id so two requests on the same chat can't interleave
    their history reads and writes. Locks are dropped once nobody holds them."""

    def __init__(self):
        self._locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()

    def get(self, session_id: str) -> asyncio.Lock:
        lock = self._locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[session_id] = lock
        return lock


def create_app(settings: Settings | None = None, gateway: LLMGateway | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    store = ChatStore(settings.database_path)
    gateway = gateway or LLMGateway(
        keys=build_key_pool(settings),
        cache_enabled=settings.cache_enabled,
        cache_ttl_seconds=settings.cache_ttl_seconds,
        timeout_seconds=settings.llm_timeout_seconds,
    )
    locks = SessionLocks()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        store.init_schema()
        log.info(
            "ready: %d key(s), models=%s, cache=%s, failure simulation=%s",
            len(gateway.keys),
            sorted({k.model for k in gateway.keys}),
            gateway.cache_enabled,
            settings.enable_failure_simulation,
        )
        yield

    app = FastAPI(title="Resilient LLM Chatbot", version="1.0.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.store = store
    app.state.gateway = gateway

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Simulate-Failure"],
    )

    @app.exception_handler(Exception)
    async def unhandled_error(_: Request, exc: Exception):
        log.exception("unhandled error", exc_info=exc)
        return JSONResponse(status_code=500, content={"detail": "internal server error"})

    @app.get("/health", response_model=HealthResponse)
    async def health():
        if not gateway.keys:
            raise HTTPException(status_code=503, detail="no API keys configured")
        if not await store.ping():
            raise HTTPException(status_code=503, detail="database unavailable")
        return HealthResponse(
            status="ok",
            keys_configured=len(gateway.keys),
            cache_enabled=gateway.cache_enabled,
            models=sorted({k.model for k in gateway.keys}),
            failure_simulation=settings.enable_failure_simulation,
        )

    @app.post("/chat", response_model=ChatResponse)
    async def chat(
        body: ChatRequest,
        x_simulate_failure: str | None = Header(default=None, alias="X-Simulate-Failure"),
    ):
        started = time.perf_counter()

        simulated = {}
        if settings.enable_failure_simulation:
            try:
                simulated = parse_simulation_header(x_simulate_failure)
            except InvalidSimulationHeader as exc:
                raise HTTPException(status_code=422, detail=f"invalid X-Simulate-Failure header: {exc}")

        # system_prompt: omitted -> keep the session's prompt, "" -> back to the default
        prompt_override = body.system_prompt.strip() if body.system_prompt is not None else None

        async with locks.get(body.session_id):
            session = await store.get_session(body.session_id)
            if prompt_override is not None:
                system_prompt = prompt_override or None
            else:
                system_prompt = session["system_prompt"] if session else None

            history = await store.get_messages(body.session_id, limit=settings.history_max_messages)
            messages = [{"role": "system", "content": system_prompt or settings.default_system_prompt}]
            messages += [{"role": m["role"], "content": m["content"]} for m in history]
            messages.append({"role": "user", "content": body.message})

            try:
                result = await gateway.complete(messages, simulated_failures=simulated)
            except AllProvidersUnavailable as exc:
                # which keys failed and why (error type + status only, never the key)
                return JSONResponse(
                    status_code=503,
                    content={
                        "detail": "all providers unavailable",
                        "failures": [{"key_id": k, "error": reason} for k, reason in exc.failures],
                    },
                )

            metadata = ChatMetadata(
                resolution_source=result.resolution_source,
                model=result.model,
                latency_ms=max(1, round((time.perf_counter() - started) * 1000)),
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                key_id=result.key_id,
                fallback_attempts=result.fallback_attempts,
            )
            await store.save_exchange(
                session_id=body.session_id,
                user_message=body.message,
                assistant_message=result.reply,
                metadata=metadata.model_dump(),
                system_prompt=system_prompt,
                update_system_prompt=prompt_override is not None,
            )

        return ChatResponse(session_id=body.session_id, reply=result.reply, metadata=metadata)

    @app.get(
        "/sessions/{session_id}/messages",
        response_model=HistoryResponse,
        response_model_exclude_none=True,
    )
    async def session_messages(session_id: str):
        if await store.get_session(session_id) is None:
            raise HTTPException(status_code=404, detail="session not found")
        return HistoryResponse(session_id=session_id, messages=await store.get_messages(session_id))

    return app


app = create_app()
