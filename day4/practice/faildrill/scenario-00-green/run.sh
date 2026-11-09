#!/usr/bin/env bash
# 场景 S1（GRAPH.md §7）：出厂 config.yaml，无注入 —— 全绿交付（B1）
# 期望：3 次 Popen 同轮派发（真并行）→ 3 个 shard → REPORT 三行全 ok → verdict=DELIVERED → 退出码 0。

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
cd "$ROOT"

SCENARIO="S1-green"
SCENARIO_DIR="faildrill/scenario-00-green"
CONFIG="config.yaml"                       # ← 出厂阈值，一个都不改
OUT="runs/$SCENARIO-$(date +%Y%m%d-%H%M%S)"
EXPECTED_EXIT=0
CMDLINE="python3 orchestrator.py --config $CONFIG --scenario $SCENARIO --out $OUT"

echo "== 场景 S1 全绿（无注入）=="
echo "config=$CONFIG  out=$OUT  期望退出码=$EXPECTED_EXIT"

python3 orchestrator.py --config "$CONFIG" --scenario "$SCENARIO" --out "$OUT" > "$HERE/run.out" 2>&1
RC=$?
cat "$HERE/run.out"

echo "$OUT" > "$HERE/LAST_RUN"
source faildrill/_checks.sh
write_meta "$OUT" "$SCENARIO" "$SCENARIO_DIR" "$CONFIG" "$RC" "$EXPECTED_EXIT" "$CMDLINE" "none"

echo
echo "-- REPORT 节点行 --"
grep -E '^\| [0-9]+ \| worker-' "$OUT/REPORT.md"
echo

fd_start "$OUT/CHECKS.txt"

check_eq "orchestrator 退出码 = 0" "$RC" "$EXPECTED_EXIT"
check    "REPORT verdict = DELIVERED"           grep -q 'verdict: \*\*DELIVERED\*\*' "$OUT/REPORT.md"
check    "REPORT 判定为全绿交付"                 grep -q '✅ 全绿交付' "$OUT/REPORT.md"
check    "state.json verdict/exit_code 一致" \
  json_true "$OUT/state.json" "d['verdict']=='DELIVERED' and d['exit_code']==0"
check    "没有覆盖任何阈值（全用出厂值）" \
  json_true "$OUT/state.json" "d['overridden_keys'] == []"

# fan-out / fan-in：3 个进程同轮派发，墙钟 < 三台耗时之和
count_ge "同一轮派发 3 个进程（3 条 DISPATCH）" 3 ev_lines "$OUT/logs/orchestrator.log" 'event=DISPATCH'
check    "FANOUT_DONE 记 dispatch_count=3 且写明 Popen 之间无 wait" \
  grep -q 'event=FANOUT_DONE round=1 .*dispatch_count=3 .*no wait() between Popen calls' "$OUT/logs/orchestrator.log"
check    "PARALLEL_EVIDENCE 判为 concurrent=True" grep -q 'event=PARALLEL_EVIDENCE round=1 .*concurrent=True' "$OUT/logs/orchestrator.log"
check    "墙钟 < 三台耗时之和（round_wall_s < sum_attempt_s）" \
  json_true "$OUT/state.json" "d['wall_s'] < sum(n['total_duration_s'] for n in d['nodes'])"
check_deadline_matches "每条 DISPATCH 的 deadline − 派发时刻 == per_node_timeout=8" "$OUT/logs/orchestrator.log" 8.0

# 每节点一行 + 产物齐 + 一次成功
count_ge "REPORT 三行全 ok" 3 ev_lines "$OUT/REPORT.md" '| \*\*ok\*\* | 1 | shards/0[0-9]\.json'
for w in 01 02 03; do
  check    "worker-$w 产物存在"                  test -e "$OUT/shards/$w.json"
  check    "worker-$w 日志存在"                  test -e "$OUT/logs/worker-$w.round1.log"
  check_empty "worker-$w stderr 为 0 字节（无报错可吞）" "$OUT/logs/worker-$w.round1.err"
  count_ge "worker-$w 回显读到的全部 11 个阈值键" 11 ev_lines "$OUT/logs/worker-$w.round1.log" 'event=CONFIG_READ'
  check    "shard 里带 pid/round/耗时/config_read" \
    json_true "$OUT/shards/$w.json" "d['status']=='ok' and d['round']==1 and d['pid']>0 and len(d['config_read'])==11"
done
count_ge "orchestrator 回显 11 个 CONFIG_LOADED 键" 11 ev_lines "$OUT/logs/orchestrator.log" 'event=CONFIG_LOADED'
check    "config.resolved.yaml 与出厂阈值一致"      grep -q 'per_node_timeout: 8' "$OUT/config.resolved.yaml"
check    "REPORT 分支命中只报 all_green_deliver"    grep -qE '\| B1 \| `branch=all_green_deliver` \| 3 \|' "$OUT/REPORT.md"
check    "REPORT 显式列出没走到的分支"              grep -q '没走到' "$OUT/REPORT.md"
check    "state.json 带代码版本指纹" \
  json_true "$OUT/state.json" "bool(d['code_sha256'].get('orchestrator.py')) and bool(d['code_sha256'].get('worker.py'))"
check    "无人工分支"                              grep -q '无人工分支' "$OUT/REPORT.md"

check "日志引用的 worker_log/worker_err/artifact 全部真实存在" refs_integrity "$OUT"

fd_finish
exit $?
