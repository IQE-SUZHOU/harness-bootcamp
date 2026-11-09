#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
work="$(mktemp -d)"
srv_pid=""

cleanup() {
  if [[ -n "$srv_pid" ]]; then kill "$srv_pid" 2>/dev/null || true; fi
  rm -rf "$work"
}
trap cleanup EXIT

run_case() {
  local title="$1"
  shift
  rm -rf "$work/run"
  mkdir -p "$work/run"

  local port_file="$work/port"
  rm -f "$port_file"
  python3 "$repo_root/tests/fake_llm.py" --port-file "$port_file" --delay 0 "$@" &
  srv_pid=$!
  for _ in $(seq 1 100); do [[ -s "$port_file" ]] && break; sleep 0.05; done
  [[ -s "$port_file" ]] || { echo "FAIL loop: fake llm did not start" >&2; exit 1; }
  local port
  port="$(cat "$port_file")"

  echo
  echo "=== $title ==="
  local rc=0
  BASE_URL="http://127.0.0.1:$port/v1" API_KEY=fake MODEL=fake \
    python3 "$repo_root/src/harness.py" \
      --task "$repo_root/tasks/demo_20.json" \
      --state "$work/run/state.json" >"$work/run/out.log" 2>&1 || rc=$?
  if [[ "$(wc -l <"$work/run/out.log")" -le 8 ]]; then
    cat "$work/run/out.log"
  else
    sed -n '1,6p' "$work/run/out.log"
    echo "..."
    tail -2 "$work/run/out.log"
  fi
  echo "exit=$rc"

  python3 "$repo_root/src/verify.py" "$work/run/state.json" >/dev/null
  echo "state invariants: OK"
  python3 - "$work/run/state.json" <<'PY'
import json
import sys

state = json.load(open(sys.argv[1]))
attempts = len(state.get("attempts", []))
print(f"status={state['status']} done={state['done']} attempts={attempts}")
PY

  kill "$srv_pid" 2>/dev/null || true
  wait "$srv_pid" 2>/dev/null || true
  srv_pid=""

  case "$title" in
    场景1*) [[ "$rc" -eq 0 ]] || { echo "FAIL loop: retry case should finish" >&2; exit 1; } ;;
    场景2*) [[ "$rc" -eq 1 ]] || { echo "FAIL loop: block case should exit 1" >&2; exit 1; } ;;
  esac
}

echo "LOCAL FAKE MODEL DEMO — 验证循环逻辑，不调用真实 LLM；真实模型用 make loop-real"

run_case "场景1：第一次不合格，带反馈重试后跑完" --fail-first 1
run_case "场景2：一直不合格，3 次后 blocked 停住" --always-bad

echo
echo "PASS loop: retry recovers, exhaustion blocks"
