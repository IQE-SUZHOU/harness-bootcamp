#!/usr/bin/env bash
# 场景 S4（GRAPH.md §7）：hang_nodes=[worker-02] + slow_nodes={worker-02: 30}
#   —— 一台既跑不完、又对 SIGTERM 无反应的模拟 GPU 测试机（死锁/挂死）
# 期望走到的分支（GRAPH.md §2 B4 强杀路径）：
#   branch=node_timeout → event=PROC_TERMINATE →(扛过 kill_grace_seconds=1)→ event=PROC_KILL
#   → branch=manual_escalation + needs_human=True → 退出码 11；worker 侧停在 SIGNAL_RECEIVED、以 -9 收场。

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
cd "$ROOT"

SCENARIO="S4-hang-worker-02"
SCENARIO_DIR="faildrill/scenario-03-hang-worker-02"
CONFIG="$SCENARIO_DIR/config.yaml"
OUT="runs/$SCENARIO-$(date +%Y%m%d-%H%M%S)"
EXPECTED_EXIT=11
CMDLINE="python3 orchestrator.py --config $CONFIG --scenario $SCENARIO --out $OUT"

echo "== 场景 S4 hang_nodes=[worker-02]（SIGTERM 叫不动 → 必然 SIGKILL）=="
echo "config=$CONFIG  out=$OUT  期望退出码=$EXPECTED_EXIT"

python3 orchestrator.py --config "$CONFIG" --scenario "$SCENARIO" --out "$OUT" > "$HERE/run.out" 2>&1
RC=$?
cat "$HERE/run.out"

echo "$OUT" > "$HERE/LAST_RUN"
source faildrill/_checks.sh
write_meta "$OUT" "$SCENARIO" "$SCENARIO_DIR" "$CONFIG" "$RC" "$EXPECTED_EXIT" "$CMDLINE" "none（注入写在场景 config 里）"

echo
echo "-- REPORT 节点行 --"
grep -E '^\| [0-9]+ \| worker-' "$OUT/REPORT.md"
echo

fd_start "$OUT/CHECKS.txt"

check_eq "orchestrator 退出码 = 11（人工分支）" "$RC" "$EXPECTED_EXIT"
check    "REPORT verdict = TIMEOUT_MANUAL"          grep -q 'verdict: \*\*TIMEOUT_MANUAL\*\*' "$OUT/REPORT.md"
check    "REPORT 明确不交付（无假成功）"             grep -q '❌ 不交付' "$OUT/REPORT.md"

# 强杀路径：越界 → SIGTERM →（宽限用尽）→ SIGKILL，且宽限值就是 config 里的 kill_grace_seconds
check    "先判越界（branch=node_timeout per_node_timeout=8）" \
  grep -q 'branch=node_timeout.*per_node_timeout=8' "$OUT/logs/orchestrator.log"
check    "先 SIGTERM（event=PROC_TERMINATE node=worker-02 grace_s=1.0）" \
  grep -q 'event=PROC_TERMINATE node=worker-02.*grace_s=1.0' "$OUT/logs/orchestrator.log"
check    "再 SIGKILL（event=PROC_KILL ... kill_grace_seconds=1.0）" \
  grep -q 'event=PROC_KILL node=worker-02.*kill_grace_seconds=1.0' "$OUT/logs/orchestrator.log"
check_event_gap "SIGTERM→SIGKILL 之间确实等满了 kill_grace_seconds=1s" \
  "$OUT/logs/orchestrator.log" 'event=PROC_TERMINATE node=worker-02' 'event=PROC_KILL node=worker-02' 1.0
check    "走人工分支（node=worker-02 branch=manual_escalation needs_human=True）" \
  grep -q 'node=worker-02.*branch=manual_escalation.*needs_human=True' "$OUT/logs/orchestrator.log"

# worker 侧现场：叫不动（对 SIGTERM 只记录不退出），最后被强杀
check    "worker-02 记录 SIGNAL_RECEIVED signal=SIGTERM action=ignored" \
  grep -q 'event=SIGNAL_RECEIVED node=worker-02.*signal=SIGTERM.*action=ignored' "$OUT/logs/worker-02.round1.log"
check    "worker-02 的注入判定写清了 hang_hit=True" \
  grep -q 'event=INJECTION_EVAL node=worker-02.*hang_hit=True' "$OUT/logs/worker-02.round1.log"
check_not "worker-02 没有 WORK_END（被 SIGKILL，没写完）" 'event=WORK_END' "$OUT/logs/worker-02.round1.log"
check_nonempty "worker-02 stderr 非空（记录它无视了 SIGTERM）" "$OUT/logs/worker-02.round1.err"
check    "stderr 里能看到 ignoring SIGTERM"          grep -q 'ignoring SIGTERM' "$OUT/logs/worker-02.round1.err"
check    "挂死节点不产 shard（shards/02.json 不存在）" test ! -e "$OUT/shards/02.json"

# 状态：killed=True、exit_code=-9（SIGKILL），且 attempts=1（超时不走重试）
check_eq "worker-02 status/exit_code/attempts = timeout / -9 / 1" \
  "$(state_get "$OUT/state.json" "[[n['status'], n['exit_code'], n['attempts']] for n in d['nodes'] if n['node']=='worker-02'][0]")" \
  "['timeout', -9, 1]"
check    "attempt 明细记 terminated=True killed=True" \
  json_true "$OUT/state.json" "[[a['terminated'], a['killed']] for n in d['nodes'] if n['node']=='worker-02' for a in n['attempts_detail']][0] == [True, True]"
check_not "没有重试分支（超时不自动重试）" 'branch=(retries_exhausted|node_failed_retry)' "$OUT/logs/orchestrator.log"

# 另两台不受牵连
check    "worker-01 / worker-03 均 ok 且有产物" \
  json_true "$OUT/state.json" "all(n['status']=='ok' for n in d['nodes'] if n['node'] in ('worker-01','worker-03'))"
check    "worker-01 产物存在"                        test -e "$OUT/shards/01.json"
check    "worker-03 产物存在"                        test -e "$OUT/shards/03.json"

# 并行与引用完整性
check    "首轮 PARALLEL_EVIDENCE 判为 concurrent=True" grep -q 'event=PARALLEL_EVIDENCE round=1 .*concurrent=True' "$OUT/logs/orchestrator.log"
check    "REPORT 人工分支小节非空"                   grep -q 'status=timeout branch=manual_escalation' "$OUT/REPORT.md"
check    "REPORT 尝试明细里 worker-02 那行 killed=True" grep -qE 'worker-02 \| 1 \| [0-9]+ \| -9 \|.*True \| True' "$OUT/REPORT.md"
check "日志引用的 worker_log/worker_err/artifact 全部真实存在" refs_integrity "$OUT"

fd_finish
exit $?
