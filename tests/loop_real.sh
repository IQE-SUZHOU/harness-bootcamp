#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
work="$(mktemp -d)"

cleanup() {
  rm -rf "$work"
}
trap cleanup EXIT

cp "$repo_root/src/harness.py" "$repo_root/src/.env" "$work/"

echo "[loop-real] 真实 LLM，20 步，逐步打印；慢网关下单步可能要几十秒"
timeout "${RUN_TIMEOUT:-1800}" python3 "$work/harness.py"
python3 "$repo_root/src/verify.py" "$work/state.json"

echo "PASS loop-real: 20 步由真实模型完成，状态不变量通过"
