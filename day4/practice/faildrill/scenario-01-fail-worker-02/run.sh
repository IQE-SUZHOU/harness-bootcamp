#!/usr/bin/env bash
# 场景 S2（GRAPH.md §7）：fail_nodes=[worker-02] —— 一台模拟 GPU 测试机挂掉
# 期望走到的分支（GRAPH.md §2）：B2 重试 → B3 重试耗尽 status=failed → B7 失败传播（主流程退出码 10）
# 同时期望：worker-01 / worker-03 照常完成并交产物；worker-02 三次尝试的 stderr 都落盘。

set -uo pipefail   # 故意不用 set -e：orchestrator 的非 0 退出码是"预期结果"，要拿来判定

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
cd "$ROOT"

SCENARIO="S2-fail-worker-02"
SCENARIO_DIR="faildrill/scenario-01-fail-worker-02"
CONFIG="$SCENARIO_DIR/config.yaml"
OUT="runs/$SCENARIO-$(date +%Y%m%d-%H%M%S)"
EXPECTED_EXIT=10
CMDLINE="python3 orchestrator.py --config $CONFIG --scenario $SCENARIO --out $OUT"

echo "== 场景 S2 fail_nodes=[worker-02] =="
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

check_eq "orchestrator 退出码非 0 且为 10（失败已传播）" "$RC" "$EXPECTED_EXIT"
check    "REPORT verdict = NODE_FAILED"           grep -q 'verdict: \*\*NODE_FAILED\*\*' "$OUT/REPORT.md"
check    "REPORT 明确不交付（无假成功）"           grep -q '❌ 不交付' "$OUT/REPORT.md"
check    "state.json verdict/exit_code 与 REPORT 一致" \
  json_true "$OUT/state.json" "d['verdict']=='NODE_FAILED' and d['exit_code']==10"
check    "worker-02 在 REPORT 里被标 failed"       grep -qE 'worker-02 \| \*\*failed\*\*' "$OUT/REPORT.md"
check    "failed 行带原因（exit 3 模拟故障）"      grep -qE 'worker-02 \| \*\*failed\*\*.*exit 3' "$OUT/REPORT.md"
check    "failed 行无产物引用（artifact = —）"     grep -qE 'worker-02 \| \*\*failed\*\* \| 3 \| — \|' "$OUT/REPORT.md"

# 重试分支确实被走到：两次 node_failed_retry + 一次 retries_exhausted（证据词逐字取自 GRAPH §2）
count_ge "重试分支被走到（branch=node_failed_retry 命中 ≥ 2）" 2 ev_lines "$OUT/logs/orchestrator.log" 'branch=node_failed_retry'
check    "重试耗尽后标 failed（branch=retries_exhausted）" grep -q 'branch=retries_exhausted' "$OUT/logs/orchestrator.log"
check    "耗尽口径来自 config（max_retries=2 被回显）"     grep -q 'branch=retries_exhausted.*max_retries=2' "$OUT/logs/orchestrator.log"

# 尝试次数：首跑 + 2 次重试 = 3 次，且三次都是独立 PID、各自有日志与 stderr
check_eq "worker-02 尝试次数 = 1 + max_retries = 3" \
  "$(state_get "$OUT/state.json" "[n['attempts'] for n in d['nodes'] if n['node']=='worker-02'][0]")" "3"
check    "worker-02 三次尝试 PID 全不同（真进程）" \
  json_true "$OUT/state.json" "len({a['pid'] for n in d['nodes'] if n['node']=='worker-02' for a in n['attempts_detail']}) == 3"
for r in 1 2 3; do
  check "worker-02 第 $r 次尝试日志落盘" test -e "$OUT/logs/worker-02.round$r.log"
  check_nonempty "worker-02 第 $r 次尝试的 stderr 已落盘且非空" "$OUT/logs/worker-02.round$r.err"
done
check    "worker 侧如实记录故障（exit_code=3 + fail_hit=True）" \
  grep -q 'event=WORK_END node=worker-02.*status=failed.*exit_code=3' "$OUT/logs/worker-02.round1.log"
check    "worker 读到注入的 fail_nodes 值"          grep -q 'fail_hit=True' "$OUT/logs/worker-02.round1.log"
check    "报错原文进了 .err（模拟 GPU 故障的 stderr）" grep -q 'simulated GPU fault' "$OUT/logs/worker-02.round1.err"

# 挂掉的节点没有产物；另外两台照常完成、其 stderr 为 0 字节（没有报错可吞）
check    "失败节点不产 shard（shards/02.json 不存在）" test ! -e "$OUT/shards/02.json"
check_eq "worker-01 状态 ok" \
  "$(state_get "$OUT/state.json" "[n['status'] for n in d['nodes'] if n['node']=='worker-01'][0]")" "ok"
check_eq "worker-03 状态 ok" \
  "$(state_get "$OUT/state.json" "[n['status'] for n in d['nodes'] if n['node']=='worker-03'][0]")" "ok"
check    "worker-01 产物存在"                        test -e "$OUT/shards/01.json"
check    "worker-03 产物存在"                        test -e "$OUT/shards/03.json"
check_empty "worker-01 stderr 为空（成功节点没有报错）"   "$OUT/logs/worker-01.round1.err"
check_empty "worker-03 stderr 为空（成功节点没有报错）"   "$OUT/logs/worker-03.round1.err"
check    "OK 节点只尝试 1 次（未受牵连）" \
  json_true "$OUT/state.json" "[n['attempts'] for n in d['nodes'] if n['node'] in ('worker-01','worker-03')] == [1, 1]"

# 真并行：首轮 3 个 PID 一次派发；重试轮只补挂掉的那台（共 5 条 DISPATCH），且首轮墙钟 < 三台耗时之和
check_eq "DISPATCH 总数 = 首轮 3 台 + 重试轮各 1 台 = 5" \
  "$(ev_lines "$OUT/logs/orchestrator.log" 'event=DISPATCH' | wc -l | tr -d ' ')" "5"
check    "首轮 fan-out 一次派发 3 个进程"            grep -q 'event=FANOUT_DONE round=1 .*dispatch_count=3' "$OUT/logs/orchestrator.log"
check    "重试轮只补派挂掉的 worker-02"              grep -q 'event=FANOUT_DONE round=2 .*nodes=\["worker-02"\] dispatch_count=1' "$OUT/logs/orchestrator.log"
check    "首轮 PARALLEL_EVIDENCE 判为 concurrent=True" grep -q 'event=PARALLEL_EVIDENCE round=1 .*concurrent=True' "$OUT/logs/orchestrator.log"
check    "重试轮单节点不谎称并行（concurrent=False）"  grep -q 'event=PARALLEL_EVIDENCE round=2 .*node_count=1 .*concurrent=False' "$OUT/logs/orchestrator.log"

# 产物引用链完整（§6.9）
check "日志引用的 worker_log/worker_err/artifact 全部真实存在" refs_integrity "$OUT"

fd_finish
exit $?
