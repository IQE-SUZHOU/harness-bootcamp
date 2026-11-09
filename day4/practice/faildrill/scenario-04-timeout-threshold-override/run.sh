#!/usr/bin/env bash
# 场景 S5（GRAPH.md §7）：同一份出厂 config.yaml，只把 per_node_timeout 从 8 覆盖成 1
#   —— 这是 §6.2"阈值不硬编码"的**可证伪实验**：只改一个阈值，行为必须随之改变。
# 期望：三台模拟机（sleep 3s）全部越过 per_node_timeout=1 → 全部走 B4 人工分支 → 退出码 11；
#       每条 DISPATCH 的 deadline_epoch − 派发时刻 = 1.000（不是写死的 8）。

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
cd "$ROOT"

SCENARIO="S5-per-node-timeout-override"
SCENARIO_DIR="faildrill/scenario-04-timeout-threshold-override"
CONFIG="config.yaml"                       # ← 出厂 config，不另建文件
OVERRIDES=(--set "per_node_timeout=1")     # ← 唯一改动：8 → 1
OUT="runs/$SCENARIO-$(date +%Y%m%d-%H%M%S)"
EXPECTED_EXIT=11
CMDLINE="python3 orchestrator.py --config $CONFIG --scenario $SCENARIO --out $OUT ${OVERRIDES[*]}"

echo "== 场景 S5 --set per_node_timeout=1（出厂默认 8）=="
echo "config=$CONFIG  out=$OUT  期望退出码=$EXPECTED_EXIT"

python3 orchestrator.py --config "$CONFIG" --scenario "$SCENARIO" --out "$OUT" "${OVERRIDES[@]}" \
  > "$HERE/run.out" 2>&1
RC=$?
cat "$HERE/run.out"

echo "$OUT" > "$HERE/LAST_RUN"
source faildrill/_checks.sh
write_meta "$OUT" "$SCENARIO" "$SCENARIO_DIR" "$CONFIG" "$RC" "$EXPECTED_EXIT" "$CMDLINE" "--set per_node_timeout=1"

echo
echo "-- REPORT 节点行 --"
grep -E '^\| [0-9]+ \| worker-' "$OUT/REPORT.md"
echo

fd_start "$OUT/CHECKS.txt"

check_eq "orchestrator 退出码 = 11" "$RC" "$EXPECTED_EXIT"
check    "REPORT verdict = TIMEOUT_MANUAL"          grep -q 'verdict: \*\*TIMEOUT_MANUAL\*\*' "$OUT/REPORT.md"

# 覆盖被记下来了（三处同源：ORCH_START overrides= / config.resolved.yaml / state.json）
check    "ORCH_START 回显 overrides=per_node_timeout=1.0" \
  grep -q 'event=ORCH_START.*overrides=.*per_node_timeout' "$OUT/logs/orchestrator.log"
check    "CONFIG_LOADED 读到的是 1.0（不是默认 8）" \
  grep -q 'event=CONFIG_LOADED key=per_node_timeout value=1.0' "$OUT/logs/orchestrator.log"
check_not "CONFIG_LOADED 里没有残留的默认值 8" \
  'event=CONFIG_LOADED key=per_node_timeout value=8' "$OUT/logs/orchestrator.log"
check    "config.resolved.yaml 落盘 per_node_timeout: 1.0" grep -q 'per_node_timeout: 1.0' "$OUT/config.resolved.yaml"
check    "state.json.overridden_keys 记了这个键" \
  json_true "$OUT/state.json" "any(o['key']=='per_node_timeout' and float(o['value'])==1.0 for o in d['overridden_keys'])"
check    "worker 也读到覆盖后的值（CONFIG_READ=1.0）" \
  grep -q 'event=CONFIG_READ.*key=per_node_timeout value=1.0' "$OUT/logs/worker-01.round1.log"

# 行为真的跟着阈值走（不是"写死 8"）：deadline = 派发时刻 + 1.000
check_deadline_matches "每条 DISPATCH 的 deadline − 派发时刻 == 覆盖后的 1s" "$OUT/logs/orchestrator.log" 1.0
check    "越界判据里回显的是 1（per_node_timeout=1.0）" \
  grep -q 'branch=node_timeout.*per_node_timeout=1.0' "$OUT/logs/orchestrator.log"
check_not "没有任何节点跑到 3s 才算超时" 'NODE_DONE.*duration_s=3\.' "$OUT/logs/orchestrator.log"

# 三台全部走人工分支，且都不重试
check_eq "三个节点全部 status=timeout attempts=1 needs_human=True" \
  "$(state_get "$OUT/state.json" "[[n['status'], n['attempts'], n['needs_human']] for n in d['nodes']]")" \
  "[['timeout', 1, True], ['timeout', 1, True], ['timeout', 1, True]]"
count_ge "三台都被 terminate（event=PROC_TERMINATE × 3）" 3 ev_lines "$OUT/logs/orchestrator.log" 'event=PROC_TERMINATE'
for w in 01 02 03; do
  count_ge "worker-$w 记下 SIGNAL_RECEIVED" 1 ev_lines "$OUT/logs/worker-$w.round1.log" 'event=SIGNAL_RECEIVED'
done
check    "三个节点都没有 shard（超时不产物）" \
  sh -c "test ! -e '$OUT/shards/01.json' && test ! -e '$OUT/shards/02.json' && test ! -e '$OUT/shards/03.json'"
check    "编排墙钟远小于默认阈值下的耗时（≈1s 级）" \
  json_true "$OUT/state.json" "d['wall_s'] < 3.0"

check "日志引用的 worker_log/worker_err/artifact 全部真实存在" refs_integrity "$OUT"

fd_finish
exit $?
