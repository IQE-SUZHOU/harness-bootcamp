#!/usr/bin/env bash
# demo.sh — 一键跑完 GRAPH.md §7 的 8 个场景（S1 全绿 … S8 坏配置），并落盘台账 runs/INDEX.md。
#
# 判定口径全部来自 GRAPH.md §2（分支）/ §5（阈值映射）/ §6（不变式）/ §7（场景清单）：
#   每个场景脚本自带断言（只读产物，不读 Python 代码），任一 FAIL ⇒ 该场景判负 ⇒ 本脚本退出码非 0。
# 用法：
#   ./demo.sh              # 跑全部 8 个场景
#   ./demo.sh S2 S7        # 只跑指定场景（按 S-id 前缀匹配）

set -uo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
source faildrill/_checks.sh

STAMP="$(date +%Y%m%d-%H%M%S)"
FILTER=("$@")

# 场景清单（与 GRAPH.md §7 一一对应）：S-id | 场景目录 | 注入/覆盖 | 期望退出码
SCENARIOS=(
  "S1-green|faildrill/scenario-00-green|无注入（出厂 config.yaml）|0"
  "S2-fail-worker-02|faildrill/scenario-01-fail-worker-02|fail_nodes=[worker-02]|10"
  "S3-slow-worker-03|faildrill/scenario-02-slow-worker-03|slow_nodes={worker-03:30}|11"
  "S4-hang-worker-02|faildrill/scenario-03-hang-worker-02|hang_nodes=[worker-02]+slow_nodes|11"
  "S5-per-node-timeout-override|faildrill/scenario-04-timeout-threshold-override|--set per_node_timeout=1|11"
  "S6-rounds-exhausted|faildrill/scenario-05-rounds-exhausted|--set max_retries=4 --set fail_nodes=[worker-01]|12"
  "S7-total-timeout|faildrill/scenario-06-total-timeout|--set total_timeout=2|13"
  "S8-config-missing-key|faildrill/scenario-07-config-missing-key|config 缺 kill_grace_seconds / 未知 --set 键|20"
)

wanted() {   # 没给过滤参数就全跑
  local sid="$1"
  [ "${#FILTER[@]}" -eq 0 ] && return 0
  local f
  for f in "${FILTER[@]}"; do
    case "$sid" in "$f"*) return 0 ;; esac
  done
  return 1
}

meta_field() {   # meta_field <meta 文件> <键>
  [ -f "$1" ] || { echo "—"; return; }
  local v
  v=$(grep -m1 -E "^$2=" "$1" 2>/dev/null | sed -E "s/^$2=//")
  echo "${v:-—}"
}

checks_summary() {   # checks_summary <CHECKS.txt>
  [ -f "$1" ] || { echo "无断言记录"; return; }
  grep -m1 '断言小结' "$1" | sed -E 's/断言小结: *//; s/ *\(明细见.*\)//'
}

declare -a TABLE=()
declare -a RUNS_OF_THIS_DEMO=()
TOTAL_FAIL=0

for entry in "${SCENARIOS[@]}"; do
  IFS='|' read -r SID DIR INJECTION EXPECTED <<< "$entry"
  wanted "$SID" || continue

  echo ""
  echo "################################################################"
  echo "# $SID   (期望退出码 $EXPECTED)"
  echo "# 注入/覆盖: $INJECTION"
  echo "################################################################"
  bash "$DIR/run.sh"
  SCRIPT_RC=$?
  [ "$SCRIPT_RC" -ne 0 ] && TOTAL_FAIL=$((TOTAL_FAIL + 1))

  RUN_DIR="$(cat "$DIR/LAST_RUN" 2>/dev/null || echo '-')"
  META="$RUN_DIR/run.sh.meta"
  [ -f "$META" ] || META="$DIR/run.sh.meta"
  CHECKS="$RUN_DIR/CHECKS.txt"
  [ -f "$CHECKS" ] || CHECKS="$DIR/CHECKS.txt"

  VERDICT="$(meta_field "$META" verdict)"
  RC_ACT="$(meta_field "$META" orchestrator_exit_code)"
  RC_STATE="$(meta_field "$META" state_exit_code)"
  SHA="$(meta_field "$META" code_sha256_orchestrator.py)"
  RUN_LABEL="$RUN_DIR"
  if [ ! -d "$RUN_DIR" ]; then RUN_LABEL="$RUN_DIR（未创建，符合期望）"; fi
  RUNS_OF_THIS_DEMO+=("$RUN_DIR")

  TABLE+=("| $SID | \`$RUN_LABEL\` | $VERDICT | $EXPECTED | $RC_ACT | $RC_STATE | $(checks_summary "$CHECKS") | $SCRIPT_RC | \`$SHA\` |")
done

echo ""
echo "################################################################"
echo "# 汇总（同一张表写进 runs/INDEX.md）"
echo "################################################################"
echo "| 场景 | run 目录 | verdict | 期望 | 实际 | state | 断言小结 | run.sh rc |"
echo "|------|----------|---------|------|------|-------|----------|-----------|"
printf '%s\n' "${TABLE[@]}" | sed -E 's/ \| `?[0-9a-f]{16}`? \|$/ |/'

# ---------------------------------------------------------------- 台账 runs/INDEX.md
# 只有"跑全部场景"才覆盖权威台账；带过滤参数的局部重跑写到 partial 文件，
# 免得一次 S5 重跑就把 INDEX 里其它场景的证据说成"更早的 run"。
if [ "${#FILTER[@]}" -gt 0 ]; then
  INDEX="runs/INDEX.partial-$STAMP.md"
  echo "（局部重跑：台账写到 $INDEX，不动 runs/INDEX.md）"
else
  INDEX="runs/INDEX.md"
fi
{
  echo "# $INDEX — 运行台账（由 demo.sh 生成于 $STAMP）"
  echo ""
  echo "场景清单的唯一权威是 \`GRAPH.md\` §7；本表只是"这一次跑了哪些 run、各自结论如何"。"
  echo ""
  echo "| 场景 | run 目录 | verdict | 期望退出码 | orchestrator 实际 | state.json | 断言小结 | run.sh rc | 代码指纹(orchestrator) |"
  echo "|------|----------|---------|-------------|--------------------|------------|----------|-----------|--------------------------|"
  printf '%s\n' "${TABLE[@]}"
  echo ""
  echo "## 每个 run 的复现入口"
  echo ""
  echo "- 场景脚本：\`faildrill/scenario-*/run.sh\`（自带断言，明细在各 run 的 \`CHECKS.txt\`）"
  echo "- 生效阈值：\`<run>/config.resolved.yaml\`；启动参数与退出码：\`<run>/run.sh.meta\`"
  echo "- 事件证据：\`<run>/logs/orchestrator.log\`（\`event=\` / \`branch=\` 逐字对应 GRAPH §2）"
  echo ""
  echo "## 全仓库 run 目录的产物引用完整性扫描（GRAPH §6.9）"
  echo ""
  echo "| run 目录 | 来源 | 扫描结果 |"
  echo "|----------|------|----------|"
  for d in runs/*/; do
    d="${d%/}"
    case "$d" in *.md) continue ;; esac
    [ -f "$d/logs/orchestrator.log" ] || continue
    origin="本次 demo"
    case " ${RUNS_OF_THIS_DEMO[*]} " in
      *" $d "*) origin="本次 demo" ;;
      *) origin="**更早的 run（非本次产出）**" ;;
    esac
    if BROKEN="$(refs_integrity "$d" 2>/dev/null)"; then
      echo "| \`$d\` | $origin | ✅ 日志引用的 worker_log/worker_err/artifact 全部存在 |"
    else
      echo "| \`$d\` | $origin | ❌ 断链引用：$(echo "$BROKEN" | tr '\n' ' ') |"
    fi
  done
  echo ""
  echo "> 更早的 run（\`green-01\`/\`green-02\`）由 12:36 那版代码产出，当时 \`worker_log=\` 曾写成"
  echo "> \`logs/01.round1.log\`（磁盘上是 \`logs/worker-01.round1.log\`）——上表把它标成断链就是这条差异。"
  echo "> 现存代码产出的等价场景是本次的 \`S1-green\`；旧目录按证据不篡改的原则原样保留。"
  echo ""
  echo "## 场景 ↔ 目录 ↔ 分支 对照"
  echo ""
  echo "见 \`GRAPH.md\` §7（S-id、注入/覆盖、必须走到的分支、期望 verdict/退出码、关键证据词）。"
} > "$INDEX"

echo ""
echo "台账：$INDEX"
if [ "$TOTAL_FAIL" -gt 0 ]; then
  echo "demo 判定：❌ 有 $TOTAL_FAIL 个场景未达预期（见上面各 CHECKS.txt）"
  exit 1
fi
echo "demo 判定：✅ ${#TABLE[@]} 个场景全部按 GRAPH §7 走到预期分支并传播退出码"
