#! /usr/bin/env bash

set -euo pipefail

BRIDGE_SUPERVISOR_PID=""
BACKEND_PID=""
BRIDGE_ENABLED="${ROBOT_BRIDGE_EMBEDDED:-false}"
PLUGIN_ENABLED="${ROBOT_PLUGIN_ENABLED:-true}"

start_bridge_supervisor() {
  if [[ "${PLUGIN_ENABLED}" != "true" || "${BRIDGE_ENABLED}" != "true" ]]; then
    return
  fi

  (
    bridge_pid=""

    handle_supervisor_stop() {
      if [[ -n "${bridge_pid}" ]] && kill -0 "${bridge_pid}" 2>/dev/null; then
        kill "${bridge_pid}" 2>/dev/null || true
        wait "${bridge_pid}" 2>/dev/null || true
      fi
      exit 0
    }

    trap handle_supervisor_stop INT TERM

    while true; do
      python -m app.plugins.robot.bridge &
      bridge_pid=$!
      wait "${bridge_pid}" || true
      sleep 1
    done
  ) &

  BRIDGE_SUPERVISOR_PID="$!"
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
  stop_process_if_running "${BRIDGE_SUPERVISOR_PID}"
}

trap cleanup EXIT INT TERM

start_bridge_supervisor

if [[ "$#" -gt 0 ]]; then
  "$@" &
else
  fastapi run --workers "${BACKEND_WORKERS:-4}" app/main.py &
fi

BACKEND_PID="$!"
wait "${BACKEND_PID}"
