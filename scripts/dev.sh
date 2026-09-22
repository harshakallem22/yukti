#!/usr/bin/env bash
# Start the API and the web dev server together, and stop both on Ctrl-C.
set -euo pipefail

cd "$(dirname "$0")/.."

PORT="${YUKTI_API_PORT:-8010}"
WEB_PORT=5173
PYTHON="${PYTHON:-.venv/bin/python}"

if [[ ! -x "$PYTHON" ]]; then
  echo "No virtualenv at $PYTHON. Run: python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'" >&2
  exit 1
fi

# --- reclaim a port left bound by a previous run ---------------------------
# uvicorn --reload spawns a child that can outlive the parent shell, so a
# stranded port is a normal outcome of Ctrl-C, not a user error.
reclaim_port() {
  local port=$1 pattern=$2 holder
  holder=$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | head -1) || true
  [[ -z ${holder:-} ]] && return 0

  if ps -p "$holder" -o command= 2>/dev/null | grep -q "$pattern"; then
    echo "Reclaiming port $port from a stale process (pid $holder)."
    kill "$holder" 2>/dev/null || true
    for _ in 1 2 3; do
      lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1 || return 0
      sleep 1
    done
    kill -9 "$holder" 2>/dev/null || true
    sleep 1
  else
    echo "Port $port is held by another process (pid $holder), not Yukti:" >&2
    ps -p "$holder" -o command= >&2
    echo "Set YUKTI_API_PORT to something else." >&2
    exit 1
  fi
}

reclaim_port "$PORT" "apps.api.app.main"
reclaim_port "$WEB_PORT" "vite"

# --- provider selection ----------------------------------------------------
# The key normally lives in .env, which only the app reads — checking just the
# shell environment would silently start real runs in scripted demo mode.
has_key=false
[[ -n "${OPENAI_API_KEY:-}" ]] && has_key=true
if [[ -f .env ]] && grep -qE '^[[:space:]]*OPENAI_API_KEY[[:space:]]*=[[:space:]]*sk-' .env; then
  has_key=true
fi

if [[ "${YUKTI_MODEL_PROVIDER:-}" == "fake" ]]; then
  echo "note: YUKTI_MODEL_PROVIDER=fake — scripted demo mode, no model calls."
elif [[ $has_key == false ]]; then
  echo "note: no OPENAI_API_KEY found (shell or .env) — starting in demo mode."
  echo "      Demo runs replay a fixed trajectory and are badged in the UI."
  export YUKTI_MODEL_PROVIDER=fake
fi

# --- run -------------------------------------------------------------------
api_pid="" web_pid=""

cleanup() {
  trap - EXIT INT TERM
  for pid in "$api_pid" "$web_pid"; do
    [[ -n $pid ]] || continue
    pkill -P "$pid" 2>/dev/null || true   # uvicorn's reload worker, vite's child
    kill "$pid" 2>/dev/null || true
  done
  sleep 1
  # Belt and braces: if either port is still bound by our own server, free it,
  # so the next run does not start by reclaiming.
  for spec in "$PORT:apps.api.app.main" "$WEB_PORT:vite"; do
    local_port=${spec%%:*}; pattern=${spec#*:}
    holder=$(lsof -nP -iTCP:"$local_port" -sTCP:LISTEN -t 2>/dev/null | head -1) || true
    if [[ -n ${holder:-} ]] && ps -p "$holder" -o command= 2>/dev/null | grep -q "$pattern"; then
      kill -9 "$holder" 2>/dev/null || true
    fi
  done
}
trap cleanup EXIT INT TERM

"$PYTHON" -m uvicorn apps.api.app.main:app --host 127.0.0.1 --port "$PORT" --reload &
api_pid=$!
(cd apps/web && npm run dev) &
web_pid=$!

echo
echo "  API  http://127.0.0.1:$PORT/docs"
echo "  Web  http://localhost:$WEB_PORT"
echo
wait
