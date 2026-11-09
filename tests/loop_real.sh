#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
state="${STATE:-/tmp/harness-loop-real/state.json}"
mkdir -p "$(dirname "$state")"

echo "[loop-real] 真实 LLM + 真实任务 tasks/rocm_triage.json（同一任务重复 3 次）"
echo "[loop-real] state=$state"
echo "[loop-real] 中断后用同一条命令重跑即可续跑；rm 掉 state 文件可从第 1 步重来"

timeout "${RUN_TIMEOUT:-1800}" python3 "$repo_root/src/harness.py" \
  --task "$repo_root/tasks/rocm_triage.json" \
  --state "$state" &
pid=$!
trap 'kill "$pid" 2>/dev/null || true' INT TERM

rc=0
wait "$pid" || rc=$?
trap - INT TERM

if [[ "$rc" -eq 3 ]]; then
  echo "FAIL loop-real: 另一个 harness 还在写同一 state；先 make stop 再重跑" >&2
  exit 3
fi
if [[ "$rc" -ne 0 ]]; then
  echo "FAIL loop-real: harness 退出码 $rc；状态已保留在 $state，重跑可续" >&2
  exit "$rc"
fi

python3 "$repo_root/src/verify.py" "$state"
echo "PASS loop-real: 真实任务跑完，状态不变量通过"
