#! /usr/bin/env bash

set -euo pipefail

BACKEND_PID=""

is_true() {
  case "${1,,}" in
    1|true|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

stop_process_if_running() {
  local pid="$1"
  if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
    kill "${pid}" 2>/dev/null || true
    wait "${pid}" 2>/dev/null || true
  fi
}

cleanup() {
  stop_process_if_running "${BACKEND_PID}"
}

trap cleanup EXIT INT TERM

if [[ "$#" -gt 0 ]]; then
  "$@" &
elif is_true "${BACKEND_AUTO_RELOAD:-false}"; then
  uvicorn app.main:app \
    --host "${BACKEND_HOST:-0.0.0.0}" \
    --port "${BACKEND_PORT:-8000}" \
    --reload \
    --reload-dir app \
    --reload-include "*.py" \
    --reload-exclude "app/services/log/*" \
    --timeout-graceful-shutdown "${BACKEND_GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS:-5}" &
else
  uvicorn app.main:app \
    --host "${BACKEND_HOST:-0.0.0.0}" \
    --port "${BACKEND_PORT:-8000}" \
    --workers "${BACKEND_WORKERS:-1}" \
    --timeout-graceful-shutdown "${BACKEND_GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS:-5}" &
fi

BACKEND_PID="$!"
wait "${BACKEND_PID}"
