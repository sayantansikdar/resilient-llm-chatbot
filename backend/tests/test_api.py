import uuid

import pytest

from .conftest import make_client, rate_limited, server_error


def new_session() -> str:
    return f"s-{uuid.uuid4().hex[:8]}"


def chat(client, session_id, message, headers=None, **extra):
    return client.post("/chat", json={"session_id": session_id, "message": message, **extra}, headers=headers or {})


# --- health -------------------------------------------------------------------

def test_health(client):
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["keys_configured"] == 2
    assert body["cache_enabled"] is True


def test_health_without_keys_is_503(tmp_path, provider):
    from app.config import Settings
    from app.llm import LLMGateway
    from app.main import create_app
    from fastapi.testclient import TestClient

    settings = Settings(api_keys=[], database_url=f"sqlite:///{tmp_path}/x.db")
    with TestClient(create_app(settings, LLMGateway(keys=[], completion_fn=provider))) as c:
        res = c.get("/health")
    assert res.status_code == 503
    assert "detail" in res.json()


# --- chat contract ------------------------------------------------------------

def test_chat_live_inference(client):
    sid = new_session()
    res = chat(client, sid, "What is the capital of France?")
    assert res.status_code == 200
    body = res.json()
    assert body["session_id"] == sid
    assert body["reply"]
    meta = body["metadata"]
    assert meta["resolution_source"] == "LIVE_INFERENCE"
    assert meta["model"] == "gemini/gemini-2.5-flash"
    assert isinstance(meta["latency_ms"], int) and meta["latency_ms"] > 0
    assert meta["input_tokens"] > 0 and meta["output_tokens"] > 0
    assert meta["key_id"] == "key_1"
    assert meta["fallback_attempts"] == 0


def test_key_secret_never_leaks(client):
    res = chat(client, new_session(), "hello")
    assert "secret-one" not in res.text and "secret-two" not in res.text


# --- caching ------------------------------------------------------------------

def test_same_first_message_in_new_session_hits_cache(client, provider):
    first = chat(client, new_session(), "What is the capital of France?").json()
    second = chat(client, new_session(), "What is the capital of France?").json()

    assert first["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert second["metadata"]["resolution_source"] == "LLM_CACHE"
    assert second["reply"] == first["reply"]
    assert second["metadata"]["key_id"] is None
    assert second["metadata"]["fallback_attempts"] == 0
    # tokens come from the stored usage of the cached response
    assert second["metadata"]["input_tokens"] == first["metadata"]["input_tokens"]
    assert second["metadata"]["output_tokens"] == first["metadata"]["output_tokens"]
    assert second["metadata"]["latency_ms"] < first["metadata"]["latency_ms"]
    assert len(provider.calls) == 1


def test_different_message_never_comes_from_cache(client):
    chat(client, new_session(), "What is the capital of France?")
    res = chat(client, new_session(), "What is the capital of Spain?").json()
    assert res["metadata"]["resolution_source"] == "LIVE_INFERENCE"


def test_cache_key_includes_history(client):
    sid = new_session()
    chat(client, sid, "hi")
    chat(client, sid, "tell me more")
    # same new message but a different history -> not a cache hit
    other = new_session()
    chat(client, other, "something else")
    res = chat(client, other, "tell me more").json()
    assert res["metadata"]["resolution_source"] == "LIVE_INFERENCE"


def test_cache_works_beyond_two_turns(client):
    """litellm's default max_messages=4 would silently disable caching here."""
    turns = ["one", "two", "three", "four"]
    a, b = new_session(), new_session()
    for t in turns:
        chat(client, a, t)
    for t in turns[:-1]:
        chat(client, b, t)
    res = chat(client, b, turns[-1]).json()
    assert res["metadata"]["resolution_source"] == "LLM_CACHE"


def test_cache_can_be_disabled(tmp_path, provider):
    with make_client(tmp_path, provider, cache_enabled=False) as c:
        assert c.get("/health").json()["cache_enabled"] is False
        chat(c, new_session(), "same")
        res = chat(c, new_session(), "same").json()
    assert res["metadata"]["resolution_source"] == "LIVE_INFERENCE"


# --- multi-turn state ---------------------------------------------------------

def test_history_is_sent_to_the_model(client, provider):
    sid = new_session()
    chat(client, sid, "My name is Asha.")
    chat(client, sid, "What is my name?")
    sent = provider.calls[-1]["messages"]
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "user"]
    assert sent[1]["content"] == "My name is Asha."
    assert sent[-1]["content"] == "What is my name?"


def test_sessions_are_isolated(client, provider):
    a, b = new_session(), new_session()
    chat(client, a, "secret word is pineapple")
    chat(client, b, "what is the secret word?")
    sent = provider.calls[-1]["messages"]
    assert all("pineapple" not in m["content"] for m in sent)


def test_tokens_are_per_request_not_cumulative(client, provider):
    a, b = new_session(), new_session()
    first_a = chat(client, a, "alpha bravo charlie").json()["metadata"]
    first_b = chat(client, b, "delta echo foxtrot").json()["metadata"]
    # equal-length first messages -> the same prompt size
    assert first_a["input_tokens"] == first_b["input_tokens"]

    second_a = chat(client, a, "golf").json()["metadata"]
    # the second turn reports only what was sent in that request
    assert second_a["input_tokens"] == sum(
        len(m["content"].split()) + 4 for m in provider.calls[-1]["messages"]
    )
    assert second_a["output_tokens"] == len("echo: golf".split())


def test_history_endpoint(client):
    sid = new_session()
    chat(client, sid, "first")
    chat(client, sid, "second")
    res = client.get(f"/sessions/{sid}/messages")
    assert res.status_code == 200
    body = res.json()
    assert body["session_id"] == sid
    msgs = body["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    assert [m["content"] for m in msgs[::2]] == ["first", "second"]
    assert "metadata" not in msgs[0]
    assert msgs[1]["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert msgs[1]["metadata"]["input_tokens"] > 0
    assert all(m["role"] != "system" for m in msgs)


def test_history_unknown_session_404(client):
    res = client.get("/sessions/does-not-exist/messages")
    assert res.status_code == 404
    assert res.json() == {"detail": "session not found"}


def test_history_survives_app_restart(tmp_path, provider):
    sid = new_session()
    with make_client(tmp_path, provider) as c:
        chat(c, sid, "remember me")
    with make_client(tmp_path, provider) as c:
        msgs = c.get(f"/sessions/{sid}/messages").json()["messages"]
    assert msgs[0]["content"] == "remember me"


# --- system prompt ------------------------------------------------------------

def test_system_prompt_override_persists_for_session(client, provider):
    sid = new_session()
    chat(client, sid, "hi", system_prompt="You are a pirate.")
    assert provider.calls[-1]["messages"][0] == {"role": "system", "content": "You are a pirate."}

    chat(client, sid, "and again")  # not sent this time, session keeps it
    assert provider.calls[-1]["messages"][0]["content"] == "You are a pirate."

    chat(client, sid, "reset", system_prompt="")
    assert provider.calls[-1]["messages"][0]["content"] != "You are a pirate."


def test_default_system_prompt_used(client, provider):
    chat(client, new_session(), "hi")
    assert provider.calls[-1]["messages"][0]["role"] == "system"


# --- validation (422) ---------------------------------------------------------

@pytest.mark.parametrize(
    "payload",
    [
        {"session_id": "s-1"},
        {"message": "hi"},
        {"session_id": "s-1", "message": ""},
        {"session_id": "s-1", "message": "   \n\t "},
        {"session_id": "", "message": "hi"},
        {"session_id": "s-1", "message": "x" * 4001},
        {"session_id": "s" * 129, "message": "hi"},
        {"session_id": "s-1", "message": 42},
    ],
)
def test_validation_errors(client, provider, payload):
    res = client.post("/chat", json=payload)
    assert res.status_code == 422
    assert "detail" in res.json()
    assert provider.calls == []


def test_message_length_counted_after_trimming(client):
    res = chat(client, new_session(), "  " + "x" * 4000 + "  ")
    assert res.status_code == 200


def test_malformed_json_is_422(client):
    res = client.post("/chat", content=b'{"session_id": "s-1", "message": ', headers={"Content-Type": "application/json"})
    assert res.status_code == 422
    assert "detail" in res.json()


def test_failed_request_not_added_to_history(client):
    sid = new_session()
    chat(client, sid, "kept")
    client.post("/chat", json={"session_id": sid, "message": ""})
    chat(client, sid, "dropped", headers={"X-Simulate-Failure": "*=429"})
    msgs = client.get(f"/sessions/{sid}/messages").json()["messages"]
    assert [m["content"] for m in msgs if m["role"] == "user"] == ["kept"]


# --- failover via X-Simulate-Failure ------------------------------------------

@pytest.mark.parametrize("status", ["429", "500", "502", "503"])
def test_simulated_key_1_failure_falls_over_to_key_2(client, status):
    res = chat(client, new_session(), "hello there", headers={"X-Simulate-Failure": f"key_1={status}"})
    assert res.status_code == 200
    meta = res.json()["metadata"]
    assert meta["key_id"] == "key_2"
    assert meta["fallback_attempts"] == 1
    assert meta["resolution_source"] == "LIVE_INFERENCE"
    assert res.json()["reply"] == "echo: hello there"


def test_simulated_all_keys_fail_is_503(client):
    sid = new_session()
    res = chat(client, sid, "hello", headers={"X-Simulate-Failure": "*=429"})
    assert res.status_code == 503
    assert res.json() == {"detail": "all providers unavailable"}
    assert client.get(f"/sessions/{sid}/messages").status_code == 404


def test_simulated_both_keys_listed_is_503(client):
    res = chat(client, new_session(), "hello", headers={"X-Simulate-Failure": "key_1=429,key_2=500"})
    assert res.status_code == 503


def test_simulation_applies_to_one_request_only(client):
    chat(client, new_session(), "warm", headers={"X-Simulate-Failure": "key_1=429"})
    res = chat(client, new_session(), "next request").json()
    assert res["metadata"]["key_id"] == "key_1"


def test_simulation_bypasses_cache_read(client):
    chat(client, new_session(), "cached question")
    res = chat(client, new_session(), "cached question", headers={"X-Simulate-Failure": "key_1=429"}).json()
    assert res["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert res["metadata"]["key_id"] == "key_2"


def test_simulation_ignored_when_disabled(tmp_path, provider):
    with make_client(tmp_path, provider, enable_failure_simulation=False) as c:
        res = chat(c, new_session(), "hello", headers={"X-Simulate-Failure": "*=429"})
    assert res.status_code == 200
    assert res.json()["metadata"]["key_id"] == "key_1"


def test_invalid_simulation_header_is_422(client):
    res = chat(client, new_session(), "hello", headers={"X-Simulate-Failure": "key_1=418"})
    assert res.status_code == 422


# --- real provider errors -----------------------------------------------------

def test_real_rate_limit_falls_over(client, provider):
    provider.fail["secret-one"] = rate_limited()
    res = chat(client, new_session(), "hello")
    assert res.status_code == 200
    assert res.json()["metadata"]["key_id"] == "key_2"
    assert res.json()["metadata"]["fallback_attempts"] == 1


def test_real_errors_on_every_key_are_503(client, provider):
    provider.fail["secret-one"] = rate_limited()
    provider.fail["secret-two"] = server_error()
    res = chat(client, new_session(), "hello")
    assert res.status_code == 503
    assert res.json() == {"detail": "all providers unavailable"}


def test_unexpected_provider_exception_is_handled(client, provider):
    provider.fail["secret-one"] = RuntimeError("socket exploded")
    provider.fail["secret-two"] = ValueError("bad payload")
    res = chat(client, new_session(), "hello")
    assert res.status_code == 503
    assert "Traceback" not in res.text


def test_empty_reply_triggers_failover(client, provider):
    provider.reply_for = lambda messages: "   "
    res = chat(client, new_session(), "hello")
    assert res.status_code == 503


def test_unknown_route_is_json(client):
    res = client.get("/nope")
    assert res.status_code == 404
    assert res.json() == {"detail": "Not Found"}
