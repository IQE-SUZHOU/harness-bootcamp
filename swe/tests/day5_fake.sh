#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
work="$(mktemp -d)"
srv_pid=""

cleanup() {
  if [[ -n "$srv_pid" ]]; then kill "$srv_pid" 2>/dev/null || true; fi
  rm -rf "$work"
}
trap cleanup EXIT

echo "LOCAL FAKE MODEL DEMO — 验证 Day5 工具链，不调用真实 LLM；真实模型用 make day5"

python3 "$repo_root/swe/tests/fake_swe_llm.py" --port-file "$work/port" & srv_pid=$!
for _ in $(seq 1 100); do [[ -s "$work/port" ]] && break; sleep 0.05; done
[[ -s "$work/port" ]] || { echo "FAIL day5-fake: fake llm did not start" >&2; exit 1; }

BASE_URL="http://127.0.0.1:$(cat "$work/port")/v1" API_KEY=fake MODEL=fake \
  python3 "$repo_root/swe/run.py" \
    --task "$repo_root/swe/tasks/bugfix_demo/task.json" \
    --run-dir "$work/run" >"$work/out.log" 2>&1 || {
      tail -20 "$work/out.log" >&2
      echo "FAIL day5-fake: agent run failed" >&2
      exit 1
    }

grep -E '^\[(step|gate|agent)\]|^PASS' "$work/out.log"
grep -q '^PASS day5' "$work/out.log" || { tail -20 "$work/out.log" >&2; exit 1; }
echo "PASS day5-fake: 脚本化模型修好 add() 且外部验证通过"
