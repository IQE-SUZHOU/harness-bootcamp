#!/usr/bin/env bash
# 场景 S8（GRAPH.md §7）：配置坏掉的两个负例
#   ① config.yaml 缺 kill_grace_seconds → 退出码 20，且不建 run 目录（不产 REPORT/shards/state）
#   ② --set 用了不存在的键（per_node_timout 拼错）→ 退出码 20，同样不产任何产物
# 期望：编排根本没起来（前置校验），报错原文落盘在场景目录 run.out，run.sh.meta 记 exit=20。

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
cd "$ROOT"

SCENARIO="S8-config-missing-key"
SCENARIO_DIR="faildrill/scenario-07-config-missing-key"
CONFIG="$SCENARIO_DIR/config.yaml"
OUT1="runs/$SCENARIO-$(date +%Y%m%d-%H%M%S)"
OUT2="runs/$SCENARIO-bad-set-key-$(date +%Y%m%d-%H%M%S)"
EXPECTED_EXIT=20

echo "== 场景 S8-① config 缺 kill_grace_seconds =="
python3 orchestrator.py --config "$CONFIG" --scenario "$SCENARIO" --out "$OUT1" > "$HERE/run.out" 2>&1
RC1=$?
cat "$HERE/run.out"

echo
echo "== 场景 S8-② --set 用了未知键 per_node_timout=1 =="
python3 orchestrator.py --config config.yaml --scenario "$SCENARIO-bad-set-key" --out "$OUT2" \
  --set "per_node_timout=1" > "$HERE/run-bad-set-key.out" 2>&1
RC2=$?
cat "$HERE/run-bad-set-key.out"

source faildrill/_checks.sh
mkdir -p "$HERE/case-bad-set-key"
echo "$OUT1" > "$HERE/LAST_RUN"
write_meta "$OUT1" "$SCENARIO" "$SCENARIO_DIR" "$CONFIG" "$RC1" "$EXPECTED_EXIT" \
  "python3 orchestrator.py --config $CONFIG --scenario $SCENARIO --out $OUT1" "none（坏在 config 里）"
write_meta "$OUT2" "$SCENARIO-bad-set-key" "$HERE/case-bad-set-key" "config.yaml" "$RC2" "$EXPECTED_EXIT" \
  "python3 orchestrator.py --config config.yaml --out $OUT2 --set per_node_timout=1" "--set per_node_timout=1（未知键）"

echo
fd_start "$SCENARIO_DIR/CHECKS.txt"

check_eq "① 缺键 → 退出码 20" "$RC1" "$EXPECTED_EXIT"
check_eq "② 未知 --set 键 → 退出码 20" "$RC2" "$EXPECTED_EXIT"
check    "① 报错原文点明了缺的键"        grep -q '缺少键: kill_grace_seconds' "$HERE/run.out"
check    "② 报错原文点明了未知键"        grep -q "未知键 'per_node_timout'" "$HERE/run-bad-set-key.out"
check    "① 没有建 run 目录（编排没起来）" test ! -d "$OUT1"
check    "② 没有建 run 目录（编排没起来）" test ! -d "$OUT2"
check    "① 没有 REPORT.md"               test ! -e "$OUT1/REPORT.md"
check    "① 没有 state.json"              test ! -e "$OUT1/state.json"
check    "① 没有任何 shards"              test ! -e "$OUT1/shards/01.json"
check    "② 没有任何 shards"              test ! -e "$OUT2/shards/01.json"
check    "① 没有 worker 日志"             test ! -e "$OUT1/logs/worker-01.round1.log"
check    "坏配置下绝不静默补默认值"       grep -q 'config 缺少键' "$HERE/run.out"
check    "① 的 run.sh.meta 落在场景目录"  test -e "$SCENARIO_DIR/run.sh.meta"
check    "② 的 run.sh.meta 落在 case 目录" test -e "$HERE/case-bad-set-key/run.sh.meta"
check    "meta 记录了 orchestrator_exit_code=20" grep -q 'orchestrator_exit_code=20' "$SCENARIO_DIR/run.sh.meta"
check    "meta 记录了 verdict=NO_RUN"     grep -q 'verdict=NO_RUN' "$SCENARIO_DIR/run.sh.meta"

fd_finish
exit $?
