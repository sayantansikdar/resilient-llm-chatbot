import asyncio
from types import SimpleNamespace

import litellm
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.llm import LLMGateway, build_key_pool
from app.main import create_app


class FakeProvider:
    """Stands in for litellm.acompletion. Records every call and can be told to
    fail for specific API keys."""

    def __init__(self, delay: float = 0.05):
        self.calls: list[dict] = []
        self.fail: dict[str, Exception] = {}  # api_key -> exception to raise
        self.delay = delay
        self.reply_for = lambda messages: f"echo: {messages[-1]['content']}"

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        await asyncio.sleep(self.delay)
        if kwargs["api_key"] in self.fail:
            raise self.fail[kwargs["api_key"]]
        messages = kwargs["messages"]
        prompt_tokens = sum(len(m["content"].split()) + 4 for m in messages)
        reply = self.reply_for(messages)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=reply))],
            usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=len(reply.split())),
        )


def rate_limited():
    return litellm.RateLimitError(message="quota exceeded", llm_provider="gemini", model="gemini-2.5-flash")


def server_error():
    return litellm.ServiceUnavailableError(message="overloaded", llm_provider="gemini", model="gemini-2.5-flash")


@pytest.fixture
def provider():
    return FakeProvider()


def make_client(tmp_path, provider, **overrides):
    options = {"enable_failure_simulation": True, **overrides}
    settings = Settings(
        api_keys=["secret-one", "secret-two"],
        database_url=f"sqlite:///{tmp_path}/test.db",
        **options,
    )
    gateway = LLMGateway(
        keys=build_key_pool(settings),
        cache_enabled=settings.cache_enabled,
        completion_fn=provider,
    )
    return TestClient(create_app(settings, gateway))


@pytest.fixture
def client(tmp_path, provider):
    with make_client(tmp_path, provider) as c:
        yield c
