#!/usr/bin/env bash
# Mona AI — one-command demo launcher.
# Starts the FastAPI backend + Next.js frontend bound to 0.0.0.0 so reviewers on
# the same Wi-Fi can open the app at http://<your-lan-ip>:3000 (not just localhost).
#
#   ./run.sh                 # real demo (Gemini, cached) — needs GEMINI_API_KEY in .env
#   LLM_PROVIDER=ollama ./run.sh   # fully local/free (needs Ollama running)
set -euo pipefail
cd "$(dirname "$0")"

# best-effort LAN IP (macOS Wi-Fi/Ethernet, then Linux, then loopback)
IP=$(ipconfig getifaddr en0 2>/dev/null \
  || ipconfig getifaddr en1 2>/dev/null \
  || hostname -I 2>/dev/null | awk '{print $1}' \
  || echo 127.0.0.1)
[ -z "$IP" ] && IP=127.0.0.1

export AUTH_MODE=dev                          # no login for the demo
export LLM_PROVIDER="${LLM_PROVIDER:-gemini}"  # gemini = real (cached) · ollama = free local
export WEB_ORIGIN="http://$IP:3000"           # let the API accept the LAN origin (CORS)

echo "────────────────────────────────────────────────────────────"
echo "  Mona AI — agent platform"
echo "    WEB : http://$IP:3000     ← open this on any device on the same Wi-Fi"
echo "    API : http://$IP:8000     (interactive docs at /docs)"
echo "    provider: $LLM_PROVIDER · auth: dev (no login)"
echo "    (single machine? use http://localhost:3000)"
echo "────────────────────────────────────────────────────────────"

# backend
uv run uvicorn api.main:app --host 0.0.0.0 --port 8000 &
API_PID=$!
trap 'kill "$API_PID" 2>/dev/null || true' EXIT INT TERM

# frontend — point the browser's API calls at the LAN IP so reviewers reach the backend
cd web
[ -d node_modules ] || npm install
NEXT_PUBLIC_API_URL="http://$IP:8000" npm run dev -- -H 0.0.0.0 -p 3000
