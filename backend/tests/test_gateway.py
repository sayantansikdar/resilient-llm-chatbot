"""Gateway tests against the real litellm.acompletion, using litellm's mock_response
so no network calls are made."""

import functools

import litellm
import pytest

from app.llm import LIVE_INFERENCE, LLM_CACHE, AllProvidersUnavailable, ApiKey, LLMGateway

MESSAGES = [
    {"role": "system", "content": "Be brief."},
    {"role": "user", "content": "What is the capital of France?"},
]


def gateway(mock_response, **kwargs):
    keys = [
        ApiKey("key_1", "gemini/gemini-3.5-flash-lite", "k1"),
        ApiKey("key_2", "gemini/gemini-3.5-flash-lite", "k2"),
    ]
    fn = functools.partial(litellm.acompletion, mock_response=mock_response)
    return LLMGateway(keys=keys, completion_fn=fn, **kwargs)


async def test_live_then_cached():
    gw = gateway("Paris.")
    live = await gw.complete(MESSAGES)
    cached = await gw.complete(MESSAGES)

    assert live.resolution_source == LIVE_INFERENCE
    assert live.reply == "Paris."
    assert live.key_id == "key_1"
    assert live.input_tokens > 0 and live.output_tokens > 0

    assert cached.resolution_source == LLM_CACHE
    assert cached.reply == live.reply
    assert cached.key_id is None
    assert (cached.input_tokens, cached.output_tokens) == (live.input_tokens, live.output_tokens)


async def test_simulated_failure_uses_litellm_exceptions():
    gw = gateway("Paris.")
    result = await gw.complete(MESSAGES, simulated_failures={"key_1": 429})
    assert result.key_id == "key_2"
    assert result.fallback_attempts == 1

    with pytest.raises(AllProvidersUnavailable) as exc:
        await gw.complete(MESSAGES, simulated_failures={"*": 503})
    assert [k for k, _ in exc.value.failures] == ["key_1", "key_2"]


def test_key_repr_hides_secret():
    assert "k1" not in repr(ApiKey("key_1", "gemini/gemini-3.5-flash-lite", "k1"))
