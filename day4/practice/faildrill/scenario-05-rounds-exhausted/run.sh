#!/usr/bin/env bash
# 场景 S6（GRAPH.md §7）：--set max_retries=4（> max_rounds-1）+ --set fail_nodes=[worker-01]
#   —— 把 GRAPH §2.1 里"出厂配置下结构性不可达"的 B6（轮次耗尽）变成有样本的分支。
# 期望：worker-01 连败 3 轮；重试预算还剩（2/4 已用）但 round=3 已是 max_rounds=3
#       → 触发退出条件 branch=rounds_exhausted → 退出码 12；绝不谎报"下一轮还会重试"。

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
cd "$ROOT"

SCENARIO="S6-rounds-exhausted"
SCENARIO_DIR="faildrill/scenario-05-rounds-exhausted"
CONFIG="config.yaml"                                    # ← 出厂 config
OVERRIDES=(--set "max_retries=4" --set "fail_nodes=[worker-01]")
OUT="runs/$SCENARIO-$(date +%Y%m%d-%H%M%S)"
EXPECTED_EXIT=12
CMDLINE="python3 orchestrator.py --config $CONFIG --scenario $SCENARIO --out $OUT ${OVERRIDES[*]}"

echo "== 场景 S6 --set max_retries=4 --set fail_nodes=[worker-01]（max_rounds=3 不变）=="
echo "config=$CONFIG  out=$OUT  期望退出码=$EXPECTED_EXIT"

python3 orchestrator.py --config "$CONFIG" --scenario "$SCENARIO" --out "$OUT" "${OVERRIDES[@]}" \
  > "$HERE/run.out" 2>&1
RC=$?
cat "$HERE/run.out"

echo "$OUT" > "$HERE/LAST_RUN"
source faildrill/_checks.sh
write_meta "$OUT" "$SCENARIO" "$SCENARIO_DIR" "$CONFIG" "$RC" "$EXPECTED_EXIT" "$CMDLINE" "--set max_retries=4 --set fail_nodes=[worker-01]"

echo
echo "-- REPORT 节点行 --"
grep -E '^\| [0-9]+ \| worker-' "$OUT/REPORT.md"
echo

fd_start "$OUT/CHECKS.txt"

check_eq "orchestrator 退出码 = 12（轮次耗尽）" "$RC" "$EXPECTED_EXIT"
check    "REPORT verdict = ROUNDS_EXHAUSTED"     grep -q 'verdict: \*\*ROUNDS_EXHAUSTED\*\*' "$OUT/REPORT.md"
check    "REPORT 明确不交付（无假成功）"          grep -q '❌ 不交付' "$OUT/REPORT.md"
check    "state.json verdict/exit_code 一致" \
  json_true "$OUT/state.json" "d['verdict']=='ROUNDS_EXHAUSTED' and d['exit_code']==12"

# 覆盖被记下来（阈值不是写死的）
check    "CONFIG_LOADED 读到 max_retries=4"      grep -q 'event=CONFIG_LOADED key=max_retries value=4' "$OUT/logs/orchestrator.log"
check    "CONFIG_LOADED 仍读到 max_rounds=3"     grep -q 'event=CONFIG_LOADED key=max_rounds value=3' "$OUT/logs/orchestrator.log"
check    "state.json.overridden_keys 记了两个覆盖" \
  json_true "$OUT/state.json" "{o['key'] for o in d['overridden_keys']} == {'max_retries', 'fail_nodes'}"

# 真的重试过（B2 有样本），但因为 max_retries=4 > max_rounds-1，耗尽的是**轮次**而不是重试预算
count_ge "重试分支被走到（branch=node_failed_retry × 2）" 2 ev_lines "$OUT/logs/orchestrator.log" 'branch=node_failed_retry'
check_not "没有 retries_exhausted（预算没用完，B3 不该命中）" 'branch=retries_exhausted' "$OUT/logs/orchestrator.log"
check    "轮次耗尽分支被走到（branch=rounds_exhausted max_rounds=3）" \
  grep -q 'branch=rounds_exhausted.*max_rounds=3' "$OUT/logs/orchestrator.log"
check    "退出原因写明 reason=rounds_exhausted"  grep -q 'event=LOOP_EXIT.*reason=rounds_exhausted' "$OUT/logs/orchestrator.log"
check    "写明「还想重试但轮次已到」"             grep -q 'branch=rounds_exhausted.*retries_remaining' "$OUT/logs/orchestrator.log"
check    "真的用满了 3 轮（rounds_used=3）"       grep -q 'event=FINAL_EXIT.*rounds_used=3' "$OUT/logs/orchestrator.log"

# 挂掉的节点：3 次尝试、无产物、needs_human=True
check_eq "worker-01 status/attempts/needs_human = rounds_exhausted / 3 / True" \
  "$(state_get "$OUT/state.json" "[[n['status'], n['attempts'], n['needs_human']] for n in d['nodes'] if n['node']=='worker-01'][0]")" \
  "['rounds_exhausted', 3, True]"
for r in 1 2 3; do
  check "worker-01 第 $r 轮日志落盘"            test -e "$OUT/logs/worker-01.round$r.log"
  check_nonempty "worker-01 第 $r 轮 stderr 非空" "$OUT/logs/worker-01.round$r.err"
done
check    "挂掉节点不产 shard（shards/01.json 不存在）" test ! -e "$OUT/shards/01.json"
check    "三次尝试 PID 全不同（真进程）" \
  json_true "$OUT/state.json" "len({a['pid'] for n in d['nodes'] if n['node']=='worker-01' for a in n['attempts_detail']}) == 3"

# 另两台不受牵连
check    "worker-02 / worker-03 ok 且有产物" \
  json_true "$OUT/state.json" "all(n['status']=='ok' for n in d['nodes'] if n['node'] in ('worker-02','worker-03'))"
check    "worker-02 产物存在"                        test -e "$OUT/shards/02.json"
check    "worker-03 产物存在"                        test -e "$OUT/shards/03.json"
check    "首轮 PARALLEL_EVIDENCE 判为 concurrent=True" grep -q 'event=PARALLEL_EVIDENCE round=1 .*concurrent=True' "$OUT/logs/orchestrator.log"
check    "REPORT 人工分支小节非空"                   grep -q 'status=rounds_exhausted' "$OUT/REPORT.md"

check "日志引用的 worker_log/worker_err/artifact 全部真实存在" refs_integrity "$OUT"

fd_finish
exit $?
