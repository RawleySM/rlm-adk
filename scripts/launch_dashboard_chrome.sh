#!/usr/bin/env bash

set -euo pipefail

dashboard_python() {
  local repo_root="$1"
  if [[ -n "${RLM_ADK_DASHBOARD_PYTHON:-}" && -x "${RLM_ADK_DASHBOARD_PYTHON}" ]]; then
    printf '%s\n' "${RLM_ADK_DASHBOARD_PYTHON}"
    return 0
  fi
  if [[ -x "${repo_root}/.venv/bin/python" ]]; then
    printf '%s\n' "${repo_root}/.venv/bin/python"
    return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return 0
  fi
  return 1
}

browser_binary() {
  if [[ -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" ]]; then
    return 1
  fi
  if command -v google-chrome >/dev/null 2>&1; then
    command -v google-chrome
    return 0
  fi
  if command -v google-chrome-stable >/dev/null 2>&1; then
    command -v google-chrome-stable
    return 0
  fi
  return 1
}

dashboard_dev_enabled() {
  local raw="${DASHBOARD_DEV:-${RLM_DASHBOARD_DEV:-}}"
  [[ "${raw,,}" =~ ^(1|true|yes|on)$ ]]
}

playwright_launcher_path() {
  local repo_root="$1"
  if [[ -n "${RLM_DASHBOARD_PLAYWRIGHT_SCRIPT:-}" ]]; then
    printf '%s\n' "${RLM_DASHBOARD_PLAYWRIGHT_SCRIPT}"
    return 0
  fi
  printf '%s\n' "${repo_root}/scripts/launch_dashboard_playwright_chrome.py"
}

launch_dashboard_viewer() {
  local repo_root="$1"
  local python_bin="$2"
  local browser_bin="$3"
  local dashboard_url="$4"

  if dashboard_dev_enabled; then
    local playwright_script
    playwright_script="$(playwright_launcher_path "${repo_root}")"
    if [[ -f "${playwright_script}" ]]; then
      nohup env \
        RLM_DASHBOARD_URL="${dashboard_url}" \
        "${python_bin}" "${playwright_script}" >/dev/null 2>&1 &
    fi
    return 0
  fi

  if [[ -n "${browser_bin}" ]]; then
    "${browser_bin}" --new-window "${dashboard_url}" >/dev/null 2>&1 &
  fi
}

dashboard_ready() {
  local python_bin="$1"
  local dashboard_url="$2"
  local dashboard_log="$3"
  local dashboard_base_url="${dashboard_url%/live}"

  if "${python_bin}" - "${dashboard_url}" <<'PY'
import sys
from rlm_adk.plugins.dashboard_auto_launch import dashboard_url_responding

raise SystemExit(0 if dashboard_url_responding(sys.argv[1]) else 1)
PY
  then
    return 0
  fi

  if "${python_bin}" - "${dashboard_log}" "${dashboard_base_url}" <<'PY'
import sys
from rlm_adk.plugins.dashboard_auto_launch import dashboard_log_reports_ready

raise SystemExit(0 if dashboard_log_reports_ready(sys.argv[1], sys.argv[2]) else 1)
PY
  then
    return 0
  fi

  return 1
}

kill_dashboard_pid() {
  local pid="$1"
  if [[ -z "${pid}" || "${pid}" == "0" ]]; then
    return 0
  fi
  kill "${pid}" >/dev/null 2>&1 || true
  for _attempt in $(seq 1 20); do
    if ! kill -0 "${pid}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.25
  done
  kill -9 "${pid}" >/dev/null 2>&1 || true
}

launch_rlm_dashboard_chrome() {
  local script_dir repo_root dashboard_host dashboard_port dashboard_url dashboard_log python_bin browser_bin
  local action target_pid instance_file fingerprint

  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  repo_root="$(cd "${script_dir}/.." && pwd)"

  if [[ "${RLM_ADK_DASHBOARD_ACTIVE:-}" =~ ^(1|true|yes)$ ]]; then
    exit 0
  fi

  dashboard_host="${RLM_ADK_DASHBOARD_HOST:-127.0.0.1}"
  dashboard_port="${RLM_ADK_DASHBOARD_PORT:-8080}"
  dashboard_url="${RLM_ADK_DASHBOARD_URL:-http://${dashboard_host}:${dashboard_port}/live}"
  dashboard_log="${repo_root}/rlm_adk/.adk/dashboard.log"

  if ! python_bin="$(dashboard_python "${repo_root}")"; then
    exit 0
  fi

  browser_bin=""
  if browser_bin="$(browser_binary 2>/dev/null)"; then
    :
  else
    browser_bin=""
  fi

  eval "$(
    "${python_bin}" - "${repo_root}" "${dashboard_url}" "${dashboard_port}" "${dashboard_log}" <<'PY'
import shlex
import sys
from pathlib import Path

from rlm_adk.plugins.dashboard_auto_launch import (
    DashboardInstanceRecord,
    compute_dashboard_fingerprint,
    dashboard_instance_file_path,
    dashboard_log_reports_ready,
    dashboard_url_responding,
    listening_pid_for_port,
    process_command_for_pid,
    resolve_dashboard_launch_plan,
)

repo_root = Path(sys.argv[1]).expanduser().resolve()
dashboard_url = sys.argv[2]
dashboard_port = int(sys.argv[3])
dashboard_log = sys.argv[4]
instance_file = dashboard_instance_file_path(repo_root)
instance_record = DashboardInstanceRecord.from_path(instance_file)
live_port_pid = listening_pid_for_port(dashboard_port)
live_port_command = process_command_for_pid(live_port_pid)
fingerprint = compute_dashboard_fingerprint(repo_root)
live_ready = dashboard_url_responding(dashboard_url)
if not live_ready and instance_record is not None:
    live_ready = dashboard_log_reports_ready(instance_record.log_path, dashboard_url.removesuffix("/live"))
plan = resolve_dashboard_launch_plan(
    current_fingerprint=fingerprint,
    dashboard_url=dashboard_url,
    dashboard_port=dashboard_port,
    instance_record=instance_record,
    live_url_responding=live_ready,
    live_port_pid=live_port_pid,
    live_port_command=live_port_command,
)

print(f"action={shlex.quote(plan.action)}")
print(f"target_pid={plan.target_pid or 0}")
print(f"instance_file={shlex.quote(str(instance_file))}")
print(f"fingerprint={shlex.quote(fingerprint)}")
print(f"dashboard_log={shlex.quote(str(dashboard_log))}")
PY
  )"

  case "${action}" in
    reuse_managed)
      launch_dashboard_viewer "${repo_root}" "${python_bin}" "${browser_bin}" "${dashboard_url}"
      exit 0
      ;;
    skip_external_service)
      exit 0
      ;;
    restart_managed|replace_unmanaged_dashboard)
      kill_dashboard_pid "${target_pid}"
      rm -f "${instance_file}"
      ;;
    start_new)
      ;;
    *)
      exit 1
      ;;
  esac

  mkdir -p "$(dirname "${dashboard_log}")"

  cd "${repo_root}"
  nohup env \
    RLM_ADK_DASHBOARD_ACTIVE=1 \
    RLM_ADK_DASHBOARD_FINGERPRINT="${fingerprint}" \
    RLM_ADK_DASHBOARD_INSTANCE_FILE="${instance_file}" \
    "${python_bin}" - "${dashboard_host}" "${dashboard_port}" >"${dashboard_log}" 2>&1 <<'PY' &
from rlm_adk.dashboard import launch_dashboard
import sys

launch_dashboard(host=sys.argv[1], port=int(sys.argv[2]), reload=False)
PY
  dashboard_pid=$!
  disown "${dashboard_pid}" 2>/dev/null || true

  for _attempt in $(seq 1 40); do
    if dashboard_ready "${python_bin}" "${dashboard_url}" "${dashboard_log}"; then
      "${python_bin}" - "${instance_file}" "${dashboard_port}" "${dashboard_url}" "${fingerprint}" "${dashboard_log}" "${dashboard_pid}" <<'PY'
import sys
from pathlib import Path
from time import strftime, gmtime

from rlm_adk.plugins.dashboard_auto_launch import DashboardInstanceRecord

instance_file = Path(sys.argv[1])
record = DashboardInstanceRecord(
    pid=int(sys.argv[6]),
    port=int(sys.argv[2]),
    url=sys.argv[3],
    fingerprint=sys.argv[4],
    started_at=strftime("%Y-%m-%dT%H:%M:%SZ", gmtime()),
    log_path=sys.argv[5],
)
record.write_to(instance_file)
PY
      launch_dashboard_viewer "${repo_root}" "${python_bin}" "${browser_bin}" "${dashboard_url}"
      exit 0
    fi
    sleep 0.25
  done

  kill_dashboard_pid "${dashboard_pid}"
  rm -f "${instance_file}"
  exit 1
}

launch_rlm_dashboard_chrome "$@"
