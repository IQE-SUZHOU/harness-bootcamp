#!/usr/bin/env bash
# 场景 S3（GRAPH.md §7）：slow_nodes={worker-03: 30} —— 一台模拟 GPU 测试机跑不完（越过 per_node_timeout）
# 期望走到的分支（GRAPH.md §2 B4）：branch=node_timeout → event=PROC_TERMINATE → branch=manual_escalation
#   → status=timeout + needs_human=True → 退出码 11，且该节点**不被自动重试**（attempts=1）。
# 本场景的 worker 响应 SIGTERM（ terminate 即止）；"扛过 SIGTERM 才被 SIGKILL" 的强杀路径由 S4 覆盖。

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
cd "$ROOT"

SCENARIO="S3-slow-worker-03"
SCENARIO_DIR="faildrill/scenario-02-slow-worker-03"
CONFIG="$SCENARIO_DIR/config.yaml"
OUT="runs/$SCENARIO-$(date +%Y%m%d-%H%M%S)"
EXPECTED_EXIT=11
CMDLINE="python3 orchestrator.py --config $CONFIG --scenario $SCENARIO --out $OUT"

echo "== 场景 S3 slow_nodes={worker-03: 30}（per_node_timeout 保持 8）=="
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

check_eq "orchestrator 退出码 = 11（超时走人工分支）" "$RC" "$EXPECTED_EXIT"
check    "REPORT verdict = TIMEOUT_MANUAL"          grep -q 'verdict: \*\*TIMEOUT_MANUAL\*\*' "$OUT/REPORT.md"
check    "REPORT 明确不交付（无假成功）"             grep -q '❌ 不交付' "$OUT/REPORT.md"
check    "state.json verdict/exit_code 一致" \
  json_true "$OUT/state.json" "d['verdict']=='TIMEOUT_MANUAL' and d['exit_code']==11"

# B4 证据链：越界 → terminate → 人工分支（阈值回显 = 判据来自 config）
check    "越界判据被记录（branch=node_timeout per_node_timeout=8）" \
  grep -q 'branch=node_timeout.*per_node_timeout=8' "$OUT/logs/orchestrator.log"
check    "真的发出过 SIGTERM（event=PROC_TERMINATE grace_s=1.0）" \
  grep -q 'event=PROC_TERMINATE node=worker-03.*grace_s=1.0' "$OUT/logs/orchestrator.log"
check    "走人工分支（branch=manual_escalation + needs_human=True）" \
  grep -q 'branch=manual_escalation.*needs_human=True' "$OUT/logs/orchestrator.log"
check    "人工分支写明不自动重试" \
  grep -q 'branch=manual_escalation.*超时不走自动重试' "$OUT/logs/orchestrator.log"

# worker 侧现场：收到 SIGTERM 并如实记录，且没有善终记录（无 WORK_END / 无 shard）
check    "worker-03 记录 SIGNAL_RECEIVED signal=SIGTERM" \
  grep -q 'event=SIGNAL_RECEIVED node=worker-03.*signal=SIGTERM' "$OUT/logs/worker-03.round1.log"
check    "worker-03 记录被杀时已睡多久（slept_so_far_s ≈ per_node_timeout）" \
  grep -qE 'event=SIGNAL_RECEIVED node=worker-03.*slept_so_far_s=(7\.[5-9]|8\.)' "$OUT/logs/worker-03.round1.log"
check_not "worker-03 没有 WORK_END（被杀，没写完）"    'event=WORK_END' "$OUT/logs/worker-03.round1.log"
check    "慢节点不产 shard（shards/03.json 不存在）"  test ! -e "$OUT/shards/03.json"
check    "超时尝试的 stderr 文件存在（§4 契约）"      test -e "$OUT/logs/worker-03.round1.err"

# 超时 ≠ 失败：不得进入重试分支（§6.4）
check_eq "worker-03 只被派发 1 次（超时不重试）" \
  "$(ev_lines "$OUT/logs/orchestrator.log" 'event=DISPATCH node=worker-03' | wc -l | tr -d ' ')" "1"
check_eq "worker-03 attempts=1 且 needs_human=True" \
  "$(state_get "$OUT/state.json" "[[n['attempts'], n['needs_human'], n['status']] for n in d['nodes'] if n['node']=='worker-03'][0]")" \
  "[1, True, 'timeout']"
check    "worker-03 记 terminated=True killed=False（响应 SIGTERM 即止）" \
  json_true "$OUT/state.json" "[[a['terminated'], a['killed']] for n in d['nodes'] if n['node']=='worker-03' for a in n['attempts_detail']][0] == [True, False]"
check_not "没有 retries_exhausted / node_failed_retry（超时不走重试）" \
  'branch=(retries_exhausted|node_failed_retry)' "$OUT/logs/orchestrator.log"

# 另外两台不受牵连
check    "worker-01 / worker-02 均 ok 且各 1 次尝试" \
  json_true "$OUT/state.json" "all(n['status']=='ok' and n['attempts']==1 for n in d['nodes'] if n['node'] in ('worker-01','worker-02'))"
check    "worker-01 产物存在"                       test -e "$OUT/shards/01.json"
check    "worker-02 产物存在"                       test -e "$OUT/shards/02.json"

# 真并行仍然成立（慢节点被杀不影响另两台的并行判定）
check    "PARALLEL_EVIDENCE 判为 concurrent=True"    grep -q 'event=PARALLEL_EVIDENCE.*concurrent=True' "$OUT/logs/orchestrator.log"
check    "REPORT 人工分支小节非空"                   grep -q 'status=timeout branch=manual_escalation' "$OUT/REPORT.md"
check    "REPORT 分支命中计数里 manual_escalation ≥ 1" grep -qE '\| B4 \| `branch=manual_escalation` \| [1-9]' "$OUT/REPORT.md"

check "日志引用的 worker_log/worker_err/artifact 全部真实存在" refs_integrity "$OUT"

fd_finish
exit $?
