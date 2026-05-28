#! /usr/bin/env bash

set -euo pipefail

BACKEND_PID=""

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
else
  fastapi run --workers "${BACKEND_WORKERS:-1}" app/main.py &
fi

BACKEND_PID="$!"
wait "${BACKEND_PID}"
