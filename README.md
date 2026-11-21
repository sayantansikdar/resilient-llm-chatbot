# Resilient LLM Chatbot

A small full-stack chat app (React + FastAPI + SQLite) that talks to Gemini through **LiteLLM**, fails over across a pool of API keys when one is rate-limited or erroring, caches responses, and shows per-request metadata (source, model, latency, tokens) next to every reply.

```
React (Vite)  ──HTTP──▶  FastAPI  ──▶  LLMGateway ──▶ LiteLLM cache (in-memory)
                           │                  └────▶ litellm.acompletion: key_1 → key_2 → … → 503
                           └──▶ SQLite (/data/app.db): sessions + messages
```

## 1. Live URLs

| | URL |
|---|---|
| Frontend | https://sikdaarrr-resilient-llm-chatbot.static.hf.space |
| Backend | https://resilient-llm-chatbot-api.onrender.com |
| Health | https://resilient-llm-chatbot-api.onrender.com/health |
| API docs | https://resilient-llm-chatbot-api.onrender.com/docs |

- **Backend** runs on Render's free plan as a Docker web service, built from `render.yaml`. Free instances sleep after 15 minutes without traffic, so **the first request after a pause can take ~30–60 s** while it wakes up. Open `/health` once before testing. Render's free plan has no persistent disk, so SQLite history lasts as long as the running instance. Locally, the `chat-data` volume keeps it across restarts.
- **Frontend** is the static build on a Hugging Face static Space, published with `scripts/deploy-frontend-hf.sh <backend-url>`.

## 2. Run locally

### With Docker

```bash
cp .env.example .env        # then put at least two real keys in LLM_API_KEYS
make up                     # builds and starts both containers
```

- Frontend: http://localhost:3000
- Backend: http://localhost:8000 (`/health`, `/docs`)

`make down` stops everything. History lives in the `chat-data` named volume mounted at `/data`, so it survives `make down && make up`; `make clean` removes the volume too. `make logs` tails both services.

### Without Docker

Backend (Python 3.12):

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
export LLM_API_KEYS=key-one,key-two
export DATABASE_URL=sqlite:///./data/app.db
export ENABLE_FAILURE_SIMULATION=true
uvicorn app.main:app --reload --port 8000
pytest -q                    # backend tests, no network or real keys needed
```

Frontend (Node 20+):

```bash
cd frontend
npm install
VITE_API_URL=http://localhost:8000 npm run dev    # http://localhost:3000
```

### Configuration

All configuration comes from environment variables (see `.env.example`).

| Variable | Default | Meaning |
|---|---|---|
| `LLM_API_KEYS` | – | Comma-separated key pool. Ids are `key_1`, `key_2`, … in this order |
| `LLM_MODEL` | `gemini/gemini-3.5-flash-lite` | LiteLLM model name used with every key |
| `LLM_MODELS` | – | Optional, one model per key (same order as the keys) to spread the pool across models |
| `DATABASE_URL` | `sqlite:///./data/app.db` (`sqlite:////data/app.db` in Docker) | SQLite file location |
| `ALLOWED_ORIGINS` | `http://localhost:3000` | Comma-separated CORS origins |
| `ENABLE_FAILURE_SIMULATION` | `false` | Enables the `X-Simulate-Failure` header |
| `DEFAULT_SYSTEM_PROMPT` | short "helpful assistant" prompt | Used when a session has no prompt of its own |
| `CACHE_ENABLED` / `CACHE_TTL_SECONDS` | `true` / `3600` | Response cache switch and lifetime |
| `LLM_TIMEOUT_SECONDS` | `30` | Per-key timeout before moving to the next key |
| `HISTORY_MAX_MESSAGES` | `40` | How many past messages are sent back to the model |
| `API_URL` (frontend container) / `VITE_API_URL` (build) | `http://localhost:8000` | Backend URL used by the browser |

## 3. Design decisions

### Key fallback

`backend/app/llm.py` holds the key pool and the failover loop. Each key becomes `key_1`, `key_2`, … with its model, and every call goes through `litellm.acompletion(model, messages, api_key=…, num_retries=0)`.

- The deployed pool is two keys from two separate Google projects (Gemini's free-tier limits are per project, so two keys in one project would be rate-limited together), both on `gemini-3.5-flash-lite` (see Bonus features for why not one model per key).
- Keys are tried **in order**. Any error from a key (LiteLLM's `RateLimitError` for 429 and quota exhaustion, `InternalServerError`/`BadGatewayError`/`ServiceUnavailableError` for 5xx, timeouts, connection errors, a revoked key, or an empty completion) is logged and the next key is tried. When every key has failed the API returns `503 {"detail": "all providers unavailable", "failures": [...]}` and nothing is written to history. `failures` lists each key id with the error type and status (for example `"RateLimitError (429)"`). It never contains the key itself, and it makes a 503 explainable without access to the server logs.
- If every key failed and some failures were **real transient errors** (5xx, timeouts, connection errors), those keys get **one more try** after ~0.6 s. Gemini's free tier returns `503 "model is experiencing high demand"` in short bursts, and a single retry clears most of them. Rate limits are not retried (retrying a 429 straight away doesn't help), and neither are simulated failures, so `*=429` still fails fast and deterministically.
- LiteLLM's own retries are switched off (`num_retries=0`) so one bad key costs one attempt, not several, and the failover order stays predictable.
- I drive the loop myself instead of using LiteLLM's `Router` fallbacks for three reasons: the response has to say exactly which key answered (`key_id`) and how many failed first (`fallback_attempts`); the order must be deterministic (key_1 before key_2); and a simulated failure must stay inside one request, whereas the Router puts failing deployments into a shared cooldown that would leak into the next request.
- `X-Simulate-Failure` raises the **same LiteLLM exception classes** a real provider error produces (429 → `RateLimitError`, 500 → `InternalServerError`, 502 → `BadGatewayError`, 503 → `ServiceUnavailableError`), so the demo goes through exactly the code path a real outage does. It is only honoured when `ENABLE_FAILURE_SIMULATION=true`; a malformed value is a 422.
- Key secrets never leave the process: responses only carry the key id, and the key object's `repr` hides the secret so it can't end up in logs or tracebacks.

### Caching

The cache is LiteLLM's built-in `Cache` (in-memory), and its own `get_cache_key` builds the key from **model + the full message list** (system prompt + history + new message). The API key is not part of the cache key, so an answer produced by key_2 is reused even when key_1 is healthy again.

- I call the cache explicitly (look up before the provider call, write right after a successful one) instead of passing `caching=True` to `acompletion`. LiteLLM writes cache entries from a background task, so an identical request sent immediately afterwards could miss; writing before the response is returned makes "the second identical request is a cache hit" deterministic.
- LiteLLM's cache skips requests with more than 4 messages by default (`max_messages=4`), which would quietly turn caching off after the second turn. The gateway sets `max_messages=None`.
- A hit returns the identical reply text and the token usage stored with the original response, with `resolution_source: LLM_CACHE`, `key_id: null` and `fallback_attempts: 0`. Hits are answered in a few milliseconds versus hundreds for a live call.
- Requests carrying `X-Simulate-Failure` skip the cache read (they still write), otherwise a failover drill on a question that was asked before would be answered from cache and never touch a key.
- In-memory means the cache resets when the container restarts. That's acceptable for this scope; the same `Cache` class can point at Redis or S3 with a config change if it ever needs to be shared between replicas.

### SQLite session storage

`backend/app/db.py`. The database path comes from `DATABASE_URL`; in Docker it is `/data/app.db` on a named volume. The schema is created on startup:

- `messages`: the table from the spec, plus a `CHECK` on `role` and an index on `(session_id, id)` for history reads.
- `sessions`: one row per session with its custom system prompt, if any. The system prompt is kept out of `messages`, so `GET /sessions/{id}/messages` returns only the conversation.

Other details:

- A user message and its reply are inserted in **one transaction**, and only after the model answered, so a failed request (422/503) leaves no trace.
- Each request opens a short-lived connection in a worker thread (`asyncio.to_thread`), so SQLite I/O never blocks the event loop. WAL mode is on.
- Requests on the same session are serialised with a per-session `asyncio.Lock`, so two quick messages can't both read the same history and interleave their writes.
- The client sends only the new message. The backend rebuilds the context from SQLite (last `HISTORY_MAX_MESSAGES` messages) on each turn.
- `system_prompt` on `/chat` sets the prompt for the session and is remembered for later turns. Sending `""` resets it to the default.

### Other notes

- `latency_ms` is measured on the server from the start of `/chat` until the reply is ready.
- Tokens are the provider's `prompt_tokens`/`completion_tokens` for that single request; nothing is summed across turns.
- Every error response is JSON with `detail`. Validation uses FastAPI's default 422 shape (messages are trimmed before the 1–4000 length check), and a catch-all handler turns anything unexpected into `{"detail": "internal server error"}` instead of a stack trace.
- Both Dockerfiles are multi-stage. The backend builds dependencies in one stage and copies only the installed packages into a `python:3.12-slim` runtime that runs as a non-root user. The frontend builds with Node and serves the static files from unprivileged nginx. The frontend container writes `API_URL` into `/env.js` at start, so the same image works against any backend.

## 4. Verification

The quickest way is `scripts/demo.sh`, which walks through every step below against the deployed backend (or `scripts/demo.sh http://localhost:8000`), pausing between steps. To run them by hand, set a base URL first:

```bash
API=https://resilient-llm-chatbot-api.onrender.com
```

**Health**

```bash
curl -s $API/health
# {"status":"ok","keys_configured":2,"cache_enabled":true,...}
```

**Cache hit.** The same first message in two new sessions:

```bash
curl -s $API/chat -H 'Content-Type: application/json' \
  -d '{"session_id":"demo-a","message":"What is the capital of France?"}'
# "resolution_source":"LIVE_INFERENCE", "key_id":"key_1", latency in the hundreds of ms

curl -s $API/chat -H 'Content-Type: application/json' \
  -d '{"session_id":"demo-b","message":"What is the capital of France?"}'
# "resolution_source":"LLM_CACHE", same reply, "key_id":null, latency a few ms
```

**Failover**

```bash
curl -s $API/chat -H 'Content-Type: application/json' -H 'X-Simulate-Failure: key_1=429' \
  -d '{"session_id":"demo-c","message":"Name a prime number above 100"}'
# 200, "key_id":"key_2", "fallback_attempts":1

curl -s $API/chat -H 'Content-Type: application/json' -H 'X-Simulate-Failure: key_1=500' \
  -d '{"session_id":"demo-c","message":"And another one?"}'
# 200, "key_id":"key_2"

curl -s -i $API/chat -H 'Content-Type: application/json' -H 'X-Simulate-Failure: *=429' \
  -d '{"session_id":"demo-c","message":"This one fails"}'
# HTTP 503 {"detail":"all providers unavailable","failures":[{"key_id":"key_1","error":"RateLimitError (429)"},...]}
# nothing stored in history
```

**Multi-turn and history**

```bash
curl -s $API/chat -H 'Content-Type: application/json' \
  -d '{"session_id":"demo-d","message":"My name is Asha, remember it."}'
curl -s $API/chat -H 'Content-Type: application/json' \
  -d '{"session_id":"demo-d","message":"What is my name?"}'
curl -s $API/sessions/demo-d/messages     # oldest first, assistant messages carry metadata
curl -s $API/sessions/nope/messages       # 404 {"detail":"session not found"}
```

**Validation**

```bash
curl -s $API/chat -H 'Content-Type: application/json' -d '{"session_id":"x","message":"   "}'   # 422
```

**In the UI**

Every assistant reply shows a badge (`LIVE_INFERENCE` in blue, `LLM_CACHE` in green), the model, the latency and `in / out` tokens for that request, plus the key that answered and how many keys failed before it. The Settings panel has the optional system prompt and a "Simulate key failure" picker. The picker sends `X-Simulate-Failure` on the next message only, which makes failover easy to show without curl. Ask the same first question after "New chat" to see a cache hit. A 503 or 422 appears as a red message in the conversation.

**Tests**

```bash
make test        # or: cd backend && pytest -q
```

63 tests cover the API contract: cache hits and misses (including caching past two turns), failover on simulated and real LiteLLM exceptions, the single retry of transient errors, the 503/422/404 cases, per-request token counts, multi-turn context, session isolation, system prompt persistence, and history surviving an app restart. Most tests use a fake provider. `test_gateway.py` goes through the real `litellm.acompletion` with LiteLLM's `mock_response`, so no network or keys are needed.

## 5. Setup Used

- **Editor:** VS Code
- **AI tools:** Claude Code (Anthropic), used as a coding assistant while building and testing the app
- **Runtime:** Python 3.12, Node 22, Docker Desktop

## 6. Bonus features

- **Failure simulation in the UI.** A picker next to the chat sends `X-Simulate-Failure` for one message, so failover can be shown live without curl.
- **Per-session system prompt that persists.** It's stored in a `sessions` table, applied from the next message, and resettable with an empty value. It never shows up in history.
- **Key pool across models.** `LLM_MODELS` can give each key its own model (for example `LLM_MODELS=gemini/gemini-3.5-flash-lite,gemini/gemini-3.1-flash-lite`), so an outage of one whole model doesn't take every key down. The `model` field shows which one answered, and the cache is checked for every model in the pool. I first deployed key_2 on `gemini-3.1-flash-lite` for exactly that reason. Over repeated calls it returned `503 "high demand"` or timed out about a quarter of the time, with roughly double the latency, while `gemini-3.5-flash-lite` answered every call. A backup key on the shakier model made failover *less* reliable, so the deployment uses `gemini-3.5-flash-lite` on both keys and relies on the transient-error retry for short bursts.
- **Extra metadata in the UI.** Besides the four required fields, each reply shows which key answered and how many failovers happened.
- **Concurrency safety.** A per-session lock serialises requests on one session, and each exchange is stored in a single transaction.
- **Hardened containers.** Both run as non-root, the backend has a Docker `HEALTHCHECK`, and the frontend gets its backend URL at runtime instead of baking it in.
- **Health reports models and simulation status.** `/health` also returns the configured models and whether failure simulation is on, which the UI uses for its status pill.
