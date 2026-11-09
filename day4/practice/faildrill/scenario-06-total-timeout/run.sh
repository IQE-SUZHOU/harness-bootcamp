#!/usr/bin/env bash
# 场景 S7（GRAPH.md §7）：--set total_timeout=2（< 单轮实际耗时 node_work_seconds=3）
#   —— 把 GRAPH §2.1 里"出厂配置下结构性不可达"的 B5（总超时）变成有样本的分支。
# 期望：轮询中途撞上 total_timeout → 在跑的 3 个进程全部 terminate → status=total_timeout
#       → 退出码 13；且 per_node_timeout=8 的单节点超时判据不得先命中（先命中就变成 B4 了）。

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
cd "$ROOT"

SCENARIO="S7-total-timeout"
SCENARIO_DIR="faildrill/scenario-06-total-timeout"
CONFIG="config.yaml"                       # ← 出厂 config（per_node_timeout 保持 8）
OVERRIDES=(--set "total_timeout=2")        # ← 唯一改动：60 → 2
OUT="runs/$SCENARIO-$(date +%Y%m%d-%H%M%S)"
EXPECTED_EXIT=13
CMDLINE="python3 orchestrator.py --config $CONFIG --scenario $SCENARIO --out $OUT ${OVERRIDES[*]}"

echo "== 场景 S7 --set total_timeout=2（单节点 sleep 3s，预算先耗尽）=="
echo "config=$CONFIG  out=$OUT  期望退出码=$EXPECTED_EXIT"

python3 orchestrator.py --config "$CONFIG" --scenario "$SCENARIO" --out "$OUT" "${OVERRIDES[@]}" \
  > "$HERE/run.out" 2>&1
RC=$?
cat "$HERE/run.out"

echo "$OUT" > "$HERE/LAST_RUN"
source faildrill/_checks.sh
write_meta "$OUT" "$SCENARIO" "$SCENARIO_DIR" "$CONFIG" "$RC" "$EXPECTED_EXIT" "$CMDLINE" "--set total_timeout=2"

echo
echo "-- REPORT 节点行 --"
grep -E '^\| [0-9]+ \| worker-' "$OUT/REPORT.md"
echo

fd_start "$OUT/CHECKS.txt"

check_eq "orchestrator 退出码 = 13（总超时）" "$RC" "$EXPECTED_EXIT"
check    "REPORT verdict = TOTAL_TIMEOUT"      grep -q 'verdict: \*\*TOTAL_TIMEOUT\*\*' "$OUT/REPORT.md"
check    "REPORT 明确不交付（无假成功）"        grep -q '❌ 不交付' "$OUT/REPORT.md"
check    "state.json verdict/exit_code 一致" \
  json_true "$OUT/state.json" "d['verdict']=='TOTAL_TIMEOUT' and d['exit_code']==13"
check    "state.json.total_timeout_hit=True" \
  json_true "$OUT/state.json" "d['total_timeout_hit'] is True"

# 阈值覆盖三处同源
check    "CONFIG_LOADED 读到 total_timeout=2.0" grep -q 'event=CONFIG_LOADED key=total_timeout value=2.0' "$OUT/logs/orchestrator.log"
check_not "CONFIG_LOADED 里没有残留默认 60" \
  'event=CONFIG_LOADED key=total_timeout value=60' "$OUT/logs/orchestrator.log"
check    "config.resolved.yaml 落盘 total_timeout: 2.0" grep -q 'total_timeout: 2.0' "$OUT/config.resolved.yaml"
check    "state.json.overridden_keys 记了这个键" \
  json_true "$OUT/state.json" "any(o['key']=='total_timeout' and float(o['value'])==2.0 for o in d['overridden_keys'])"

# B5 判据与后果：预算耗尽 → 停掉全部在跑进程（不是单节点超时）
check    "branch=total_timeout 且回显 total_timeout=2.0" \
  grep -q 'branch=total_timeout.*total_timeout=2.0' "$OUT/logs/orchestrator.log"
check_not "单节点超时判据没抢先命中（无 branch=node_timeout）" 'branch=node_timeout' "$OUT/logs/orchestrator.log"
count_ge "三个在跑进程全部被 terminate" 3 ev_lines "$OUT/logs/orchestrator.log" 'event=PROC_TERMINATE'
check_eq "三个节点 status 全为 total_timeout" \
  "$(state_get "$OUT/state.json" "sorted(n['status'] for n in d['nodes'])")" "['total_timeout', 'total_timeout', 'total_timeout']"
check    "没有节点产 shard（被中止，不产物）" \
  sh -c "test ! -e '$OUT/shards/01.json' && test ! -e '$OUT/shards/02.json' && test ! -e '$OUT/shards/03.json'"
check    "确实是被预算掐停，不是跑完（wall_s < node_work_seconds=3）" \
  json_true "$OUT/state.json" "d['wall_s'] < 3.0"
check    "每次中止都留下 worker 日志与 stderr 引用（§4 契约）" \
  json_true "$OUT/state.json" "all(a.get('worker_log') and a.get('worker_err') for n in d['nodes'] for a in n['attempts_detail'])"
check    "首轮 fan-out 仍是 3 个进程"            grep -q 'event=FANOUT_DONE round=1 .*dispatch_count=3' "$OUT/logs/orchestrator.log"
check    "首轮 PARALLEL_EVIDENCE 判为 concurrent=True" grep -q 'event=PARALLEL_EVIDENCE round=1 .*concurrent=True' "$OUT/logs/orchestrator.log"

check "日志引用的 worker_log/worker_err/artifact 全部真实存在" refs_integrity "$OUT"

fd_finish
exit $?
