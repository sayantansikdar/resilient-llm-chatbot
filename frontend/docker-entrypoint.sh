#!/bin/sh
# Runs before nginx starts (nginx image picks up /docker-entrypoint.d/*.sh).
# Writes the backend URL from the API_URL env var into /env.js so one image
# works against any backend without a rebuild.
set -eu
API_URL="${API_URL:-http://localhost:8000}"
printf 'window.__ENV__ = { API_URL: "%s" };\n' "$API_URL" > /usr/share/nginx/html/env.js
echo "frontend: API_URL=$API_URL"
