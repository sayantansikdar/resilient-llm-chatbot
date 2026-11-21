#!/usr/bin/env bash
# Build the frontend and publish it to a Hugging Face static Space.
# Usage: scripts/deploy-frontend-hf.sh <backend-url> [space-id]
set -euo pipefail

API_URL="${1:?usage: $0 <backend-url> [space-id]}"
SPACE="${2:-sikdaarrr/resilient-llm-chatbot}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

cd "$ROOT/frontend"
npm ci --no-audit --no-fund
VITE_API_URL="$API_URL" npm run build

printf 'window.__ENV__ = { API_URL: "%s" };\n' "$API_URL" > dist/env.js
cat > dist/README.md <<MD
---
title: Resilient LLM Chatbot
emoji: 💬
colorFrom: indigo
colorTo: blue
sdk: static
pinned: false
---

Frontend for https://github.com/sayantansikdar/resilient-llm-chatbot (backend: $API_URL)
MD

# python API rather than `hf upload`, which tries to (re)create the repo as a Gradio Space
SPACE="$SPACE" uv run -q --no-project --with huggingface_hub python - <<PY
import os
from huggingface_hub import HfApi
HfApi().upload_folder(
    repo_id=os.environ["SPACE"], repo_type="space", folder_path="dist",
    delete_patterns=["assets/*"], commit_message="Deploy frontend",
)
PY
echo "Deployed: https://${SPACE/\//-}.static.hf.space"
