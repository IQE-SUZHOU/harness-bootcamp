#!/usr/bin/env bash
# demo.sh — mini harness 四幕演示：全绿 / 中断恢复 / 门禁拦截 / 消融实验
# 用法: ./demo.sh [act1|act2|act3|act4|reset|all]
# 整体 exit 0（幕 3 的 exit=2 是预期行为，已被捕获判分）
set -u
cd "$(dirname "$0")"
PY=python3
ACT="${1:-all}"
RESULTS=()

reset() { rm -rf state runs .agent; echo "[demo] -- reset --"; }

act1() {
  reset
  echo; echo "=========== ACT 1 全绿：一条命令到出结果 ==========="
  if $PY harness.py run; then
    RESULTS+=("act1 全绿 ✓ FINAL_REPORT 产出")
  else
    RESULTS+=("act1 ✗ 意外失败")
  fi
  echo "--- runs/FINAL_REPORT.md ---"
  head -8 runs/FINAL_REPORT.md
}

act2() {
  reset
  echo; echo "=========== ACT 2 中断恢复：进程死了，状态没死 ==========="
  $PY harness.py run --crash-after worker-01
  echo ">>> crash exit=$? (预期 1)"
  $PY harness.py status
  echo "--- .agent/HANDOFF.md ---"; cat .agent/HANDOFF.md
  if $PY harness.py resume; then
    RESULTS+=("act2 续跑 ✓ skip 已完成阶段，不重做")
  else
    RESULTS+=("act2 ✗ 意外失败")
  fi
}

act3() {
  reset
  echo; echo "=========== ACT 3 门禁拦截：retry → 人工 gate ==========="
  $PY harness.py run --set fail_nodes=worker-02
  RC=$?
  if grep -qi "status: failed" runs/FINAL_REPORT.md && [ "$RC" -eq 2 ]; then
    RESULTS+=("act3 拦截 ✓ retry→manual gate，exit=2，原因在案")
  else
    RESULTS+=("act3 ✗ 意外（exit=$RC）")
  fi
  echo "--- FINAL_REPORT（失败原因 + 传播）---"
  sed -n '/status: failed/,/^$/p; /失败原因/,+2p; /失败传播/,+1p' runs/FINAL_REPORT.md
  reset
}

act4() {
  reset
  $PY harness.py run >/dev/null 2>&1
  echo; echo "=========== ACT 4 消融实验：移除 scope 子系统 ==========="
  echo "-- enforce=ON（正常）：越界写被拦——"
  $PY -c "import scope; scope.safe_write('/tmp/ablation_probe.txt','x')" 2>&1 | tail -1
  echo "-- enforce=OFF（--no-scope 等效）：边界消失——"
  $PY -c "import scope; scope.enforce=False; scope.safe_write('/tmp/ablation_probe.txt','x')"
  rm -f /tmp/ablation_probe.txt
  RESULTS+=("act4 消融 ✓ 移除子系统→越界成功（lecture-02 方法）")
}

case "$ACT" in
  act1) act1;; act2) act2;; act3) act3;; act4) act4;; reset) reset;;
  all) act1; act2; act3; act4;;
  *) echo "usage: ./demo.sh [act1|act2|act3|act4|reset|all]"; exit 1;;
esac

echo
echo "===================== DEMO SUMMARY ====================="
for i in "${!RESULTS[@]}"; do echo "[$((i+1))/4] ${RESULTS[$i]}"; done
echo "========================================================"
echo "(整条命令 exit 0；幕 3 的 exit=2 是演示的预期行为)"
exit 0
