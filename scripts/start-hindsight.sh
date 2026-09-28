#!/usr/bin/env bash
# Launch a local Hindsight server (embedded pg0 Postgres + local ONNX embedder).
#
# Usage:  bash scripts/start-hindsight.sh
#
# Why this script exists:
#   * Windows consoles default to cp1252, which cannot encode Hindsight's ASCII
#     banner. Without PYTHONUTF8 the process dies with UnicodeEncodeError before
#     it ever binds a port.
#   * The default embeddings/reranker providers require sentence-transformers;
#     we use the ONNX embedder + flashrank reranker instead (lighter install).
#
# Every value below can be overridden by exporting it first; this script only
# sets defaults so the committed .env / docker-compose config stays authoritative.

set -euo pipefail
cd "$(dirname "$0")/.."

PY=".venv-hindsight/Scripts/python.exe"
[ -x "$PY" ] || PY=".venv-hindsight/bin/python"
if [ ! -x "$PY" ]; then
  echo "Hindsight venv not found. Run: make setup-hindsight" >&2
  exit 1
fi

# --- Windows console encoding fix (must come first) ---
export PYTHONUTF8="${PYTHONUTF8:-1}"
export PYTHONIOENCODING="${PYTHONIOENCODING:-utf-8}"

# --- LLM backend (OpenAI-compatible endpoint) ---
# NOTE: the model must support tool calling - Hindsight reflect drives its
# internal retrieval through tool calls and 500s without one. qwen2.5:7b does;
# llama3.2:latest (3B) emits malformed tool calls and does not.
export HINDSIGHT_API_LLM_PROVIDER="${HINDSIGHT_API_LLM_PROVIDER:-ollama}"
export HINDSIGHT_API_LLM_MODEL="${HINDSIGHT_API_LLM_MODEL:-qwen2.5:7b}"
export HINDSIGHT_API_LLM_BASE_URL="${HINDSIGHT_API_LLM_BASE_URL:-http://127.0.0.1:11434/v1}"
# Reflect's default LLM deadline is 30s (HINDSIGHT_API config.py
# DEFAULT_REFLECT_LLM_TIMEOUT). qwen2.5:7b on CPU - especially when ollama is
# also swapping the app's llama3.2 in and out - needs far more. 900s covers a
# cold model load plus a full tool-calling reflect.
export HINDSIGHT_API_LLM_TIMEOUT="${HINDSIGHT_API_LLM_TIMEOUT:-900}"

# --- Embeddings / reranking ---
export HINDSIGHT_API_EMBEDDINGS_PROVIDER="${HINDSIGHT_API_EMBEDDINGS_PROVIDER:-onnx}"
export HINDSIGHT_API_RERANKER_PROVIDER="${HINDSIGHT_API_RERANKER_PROVIDER:-flashrank}"

# --- Extraction budget: LOCAL models rarely emit 65k tokens; 16k is the
#     documented workaround and must stay above HINDSIGHT_API_RETAIN_CHUNK_SIZE.
export HINDSIGHT_API_RETAIN_MAX_COMPLETION_TOKENS="${HINDSIGHT_API_RETAIN_MAX_COMPLETION_TOKENS:-16000}"
export HINDSIGHT_API_RETAIN_CHUNK_SIZE="${HINDSIGHT_API_RETAIN_CHUNK_SIZE:-3000}"

# --- First-run model downloads (ONNX embedder + flashrank reranker) can take
#     several minutes; the 300s default aborts startup mid-download.
export HINDSIGHT_API_MODEL_INIT_TIMEOUT="${HINDSIGHT_API_MODEL_INIT_TIMEOUT:-1800}"

# --- Server binding ---
export HINDSIGHT_API_HOST="${HINDSIGHT_API_HOST:-127.0.0.1}"
export HINDSIGHT_API_PORT="${HINDSIGHT_API_PORT:-8888}"

mkdir -p .hindsight
LOG=".hindsight/hindsight.log"
echo "Starting Hindsight on ${HINDSIGHT_API_HOST}:${HINDSIGHT_API_PORT} (log: ${LOG})"

if [ "${1:-}" = "--foreground" ]; then
  exec "$PY" -m hindsight_api.main
fi

nohup "$PY" -m hindsight_api.main > "$LOG" 2>&1 &
echo "pid $!"
