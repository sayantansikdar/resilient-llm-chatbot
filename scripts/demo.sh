#!/usr/bin/env bash
# Walks through every endpoint: health, live call, cache hit, failover,
# all-keys-down, multi-turn history and validation.
#
#   scripts/demo.sh                          # against the deployed backend
#   scripts/demo.sh http://localhost:8000    # against `make up`
#   NO_PAUSE=1 scripts/demo.sh               # run straight through
set -uo pipefail

API="${1:-https://resilient-llm-chatbot-api.onrender.com}"
API="${API%/}"
RUN="$(date +%s)"               # makes questions unique per run, so step 2 is a real live call
QUESTION="What is the capital of France? (demo $RUN)"

bold=$'\e[1m'; dim=$'\e[2m'; blue=$'\e[34m'; reset=$'\e[0m'

step() {
  echo
  echo "${bold}${blue}== $1 ==${reset}"
  [ -n "${2:-}" ] && echo "${dim}$2${reset}"
}

pause() {
  [ -n "${NO_PAUSE:-}" ] && return
  read -r -p "${dim}[enter]${reset} " _
}

pretty() {
  python3 -c 'import json,sys
raw = sys.stdin.read()
try:
    print(json.dumps(json.loads(raw), indent=2)[:1500])
except ValueError:
    print(raw[:1500])'
}

# show the command, run it, print status + pretty JSON
call() {
  local method="$1" path="$2" body="${3:-}" header="${4:-}"
  local args=(-s -m 90 -w $'\n%{http_code}' -X "$method" "$API$path")
  local shown="curl -X $method $API$path"
  if [ -n "$header" ]; then args+=(-H "$header"); shown+=" -H '$header'"; fi
  if [ -n "$body" ]; then args+=(-H "Content-Type: application/json" -d "$body"); shown+=" -d '$body'"; fi
  echo "${dim}\$ $shown${reset}"
  local out status
  out="$(curl "${args[@]}")"
  status="${out##*$'\n'}"
  echo "${bold}HTTP $status${reset}"
  printf '%s' "${out%$'\n'*}" | pretty
}

echo "${bold}Resilient LLM Chatbot - API demo${reset}"
echo "Backend: $API"

step "1. Health" "Database reachable, key pool loaded, cache on."
call GET /health
pause

step "2. Live inference" "New session, new question -> LIVE_INFERENCE, answered by key_1."
call POST /chat "{\"session_id\":\"demo-a-$RUN\",\"message\":\"$QUESTION\"}"
pause

step "3. Cache hit" "Same first message in a different session -> LLM_CACHE, same reply, key_id null, a few ms."
call POST /chat "{\"session_id\":\"demo-b-$RUN\",\"message\":\"$QUESTION\"}"
pause

step "4. Failover: key_1 rate-limited" "X-Simulate-Failure: key_1=429 -> answered by key_2, fallback_attempts 1."
call POST /chat "{\"session_id\":\"demo-c-$RUN\",\"message\":\"Name one prime number above 100. ($RUN)\"}" "X-Simulate-Failure: key_1=429"
pause

step "5. Failover: key_1 server error" "X-Simulate-Failure: key_1=500 -> key_2 again."
call POST /chat "{\"session_id\":\"demo-c-$RUN\",\"message\":\"And one more?\"}" "X-Simulate-Failure: key_1=500"
pause

step "6. Every key fails" "*=429 -> clean 503 JSON, no stack trace, nothing saved."
call POST /chat "{\"session_id\":\"demo-d-$RUN\",\"message\":\"This request should fail\"}" "X-Simulate-Failure: *=429"
echo "${dim}...and the failed request was not stored:${reset}"
call GET "/sessions/demo-d-$RUN/messages"
pause

step "7. Multi-turn memory" "The client only sends the new message; history comes from SQLite."
call POST /chat "{\"session_id\":\"demo-e-$RUN\",\"message\":\"My name is Asha. Reply with just: noted.\"}"
call POST /chat "{\"session_id\":\"demo-e-$RUN\",\"message\":\"What is my name?\"}"
pause

step "8. Session history" "Oldest first, assistant messages carry their metadata, no system prompt."
call GET "/sessions/demo-e-$RUN/messages"
pause

step "9. Validation" "Blank message -> 422, unknown session -> 404."
call POST /chat '{"session_id":"demo-f","message":"   "}'
call GET "/sessions/does-not-exist-$RUN/messages"

echo
echo "${bold}Done.${reset}"
