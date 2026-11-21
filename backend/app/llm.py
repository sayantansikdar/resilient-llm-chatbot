import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import litellm
from litellm.caching.caching import Cache

from .config import Settings
from .simulation import status_for_key

log = logging.getLogger("chat.llm")

LIVE_INFERENCE = "LIVE_INFERENCE"
LLM_CACHE = "LLM_CACHE"

# litellm exception type per simulated status, so simulated failures go through
# exactly the same handling as real provider errors
_SIMULATED_ERRORS: dict[int, type[Exception]] = {
    429: litellm.RateLimitError,
    500: litellm.InternalServerError,
    502: litellm.BadGatewayError,
    503: litellm.ServiceUnavailableError,
}


@dataclass(frozen=True)
class ApiKey:
    key_id: str
    model: str
    secret: str

    def __repr__(self) -> str:  # keep secrets out of logs and tracebacks
        return f"ApiKey(key_id={self.key_id!r}, model={self.model!r})"


@dataclass(frozen=True)
class Completion:
    reply: str
    model: str
    input_tokens: int
    output_tokens: int
    resolution_source: str
    key_id: str | None
    fallback_attempts: int


class AllProvidersUnavailable(Exception):
    def __init__(self, failures: list[tuple[str, str]]):
        self.failures = failures
        super().__init__("all providers unavailable")


class EmptyCompletion(Exception):
    pass


def build_key_pool(settings: Settings) -> list[ApiKey]:
    return [
        ApiKey(key_id=f"key_{i + 1}", model=settings.model_for_key(i), secret=secret)
        for i, secret in enumerate(settings.api_keys)
    ]


def is_transient(exc: Exception | None) -> bool:
    """Server-side hiccups worth one more try; rate limits and auth errors are not."""
    if exc is None or isinstance(exc, litellm.RateLimitError):
        return False
    if isinstance(exc, (litellm.Timeout, litellm.APIConnectionError, EmptyCompletion)):
        return True
    status = getattr(exc, "status_code", None)
    return isinstance(status, int) and status >= 500


def describe_error(exc: Exception) -> str:
    status = getattr(exc, "status_code", None)
    name = type(exc).__name__
    return f"{name} ({status})" if status else name


class LLMGateway:
    """Talks to the model through LiteLLM with a response cache in front and
    ordered failover across the key pool behind it."""

    def __init__(
        self,
        keys: list[ApiKey],
        cache_enabled: bool = True,
        cache_ttl_seconds: int = 3600,
        timeout_seconds: int = 30,
        transient_retry_delay: float | None = 0.6,
        completion_fn: Callable[..., Awaitable[Any]] | None = None,
    ):
        self.keys = keys
        self.timeout_seconds = timeout_seconds
        self.transient_retry_delay = transient_retry_delay
        self._completion_fn = completion_fn or litellm.acompletion
        self.cache: Cache | None = None
        if cache_enabled:
            # max_messages=None: litellm skips caching for requests with more than
            # 4 messages by default, which would disable the cache after two turns
            self.cache = Cache(type="local", ttl=cache_ttl_seconds, max_messages=None)

    @property
    def cache_enabled(self) -> bool:
        return self.cache is not None

    def _models(self) -> list[str]:
        return list(dict.fromkeys(k.model for k in self.keys))

    async def _cache_lookup(self, messages: list[dict[str, str]]) -> Completion | None:
        if self.cache is None:
            return None
        for model in self._models():
            hit = await self.cache.async_get_cache(model=model, messages=messages)
            if isinstance(hit, dict) and hit.get("reply"):
                return Completion(
                    reply=hit["reply"],
                    model=model,
                    input_tokens=int(hit.get("input_tokens", 0)),
                    output_tokens=int(hit.get("output_tokens", 0)),
                    resolution_source=LLM_CACHE,
                    key_id=None,
                    fallback_attempts=0,
                )
        return None

    async def _cache_store(self, model: str, messages: list[dict[str, str]], result: Completion) -> None:
        if self.cache is None:
            return
        payload = {
            "reply": result.reply,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
        }
        try:
            await self.cache.async_add_cache(payload, model=model, messages=messages)
        except Exception:  # a cache write must never fail the request
            log.exception("failed to write response to cache")

    async def _call(self, key: ApiKey, messages: list[dict[str, str]]) -> tuple[str, int, int]:
        response = await self._completion_fn(
            model=key.model,
            messages=messages,
            api_key=key.secret,
            timeout=self.timeout_seconds,
            num_retries=0,  # failover is handled here, one attempt per key
        )
        content = response.choices[0].message.content
        if not content or not content.strip():
            raise EmptyCompletion(f"{key.model} returned an empty reply")
        usage = getattr(response, "usage", None)
        input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        return content.strip(), input_tokens, output_tokens

    async def _attempt(
        self,
        key: ApiKey,
        messages: list[dict[str, str]],
        simulated: int | None,
        failures: list[tuple[str, str]],
    ) -> tuple[Completion | None, Exception | None]:
        """One try with one key: (result, None) on success, (None, error) on failure."""
        try:
            if simulated is not None:
                raise _SIMULATED_ERRORS[simulated](
                    message=f"simulated {simulated} via X-Simulate-Failure",
                    llm_provider="simulation",
                    model=key.model,
                )
            reply, input_tokens, output_tokens = await self._call(key, messages)
        except Exception as exc:
            reason = describe_error(exc)
            failures.append((key.key_id, reason))
            log.warning("key %s failed (%s)", key.key_id, reason)
            return None, exc

        result = Completion(
            reply=reply,
            model=key.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            resolution_source=LIVE_INFERENCE,
            key_id=key.key_id,
            fallback_attempts=len(failures),
        )
        await self._cache_store(key.model, messages, result)
        return result, None

    async def complete(
        self,
        messages: list[dict[str, str]],
        simulated_failures: dict[str, int] | None = None,
    ) -> Completion:
        simulated_failures = simulated_failures or {}

        # A failover drill has to reach the providers, so it skips the cache read.
        # The answer it produces is still written to the cache.
        if not simulated_failures:
            cached = await self._cache_lookup(messages)
            if cached is not None:
                return cached

        failures: list[tuple[str, str]] = []
        retry_later: list[ApiKey] = []
        for key in self.keys:
            simulated = status_for_key(simulated_failures, key.key_id)
            result, error = await self._attempt(key, messages, simulated, failures)
            if result is not None:
                return result
            if simulated is None and is_transient(error):
                retry_later.append(key)

        # Every key failed. Real overload/5xx/timeout errors are often momentary
        # ("model is experiencing high demand"), so give those keys one more go.
        # Simulated failures and rate limits are not retried.
        if retry_later and self.transient_retry_delay is not None:
            await asyncio.sleep(self.transient_retry_delay)
            for key in retry_later:
                log.info("retrying %s after a transient error", key.key_id)
                result, _ = await self._attempt(key, messages, None, failures)
                if result is not None:
                    return result

        log.error("all keys failed: %s", ", ".join(f"{k}={r}" for k, r in failures))
        raise AllProvidersUnavailable(failures)
