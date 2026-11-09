#!/usr/bin/env bash
# gate.sh — Day3 maker 侧的完成门禁循环（T5）
#
# 规则：
#   1. 跑 maker（首次 mode=fresh，之后一律 --resume：中断的证据由 resume 接盘）
#   2. **判定只问 checker**：不读 maker 的退出码、不读它的 stdout 结论。
#      maker 退出码只打印出来当诊断（例如 137 = 被 kill），绝不参与判定。
#   3. checker 判 FAIL → 重试；重试上限 MAX_RETRIES=3（含首次共至多 4 次判定）。
#   4. 重试用完仍 FAIL → 升级人工：打印失败门禁 + 原因 + 证据目录，exit 2。
#   5. checker 退出码 3 = 无法判定（连判定对象/历史都拿不到）→ 不重试，直接升级人工。
#      理由：套件文件坏 / run 目录不存在这类问题不是 maker 重跑能修的，重试只是烧时间。
#   6. gate 从不写 run 目录：每次判定写一行审计记录到 .gate_log/attempts.jsonl，
#      被判定的那 5 类证据保持纯净（见 DOD 第 0 节）。
#
# 用法：
#   ./gate.sh                                  # run 目录 = <lab>/run
#   ./gate.sh --run-dir /tmp/x/run --max-retries 3 --task-seconds 0.5 --max-age 900
# 退出码：0 = 门禁 PASS；2 = 升级人工（重试耗尽 / 无法判定）
set -uo pipefail

LAB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="$LAB/run"
MAX_RETRIES=3
TASK_SECONDS=0.5
MAX_AGE=900
LOG="$LAB/.gate_log/attempts.jsonl"
MAKER="$LAB/maker/gpu_harness.py"
CHECKER="$LAB/checker.py"

usage() {  # 打印文件头的注释块（shebang 之后到第一条非注释行为止）
  awk 'NR>1 && /^#/{sub(/^# ?/,""); print; next} NR>1{exit}' "${BASH_SOURCE[0]}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-dir)     RUN_DIR="${2:?--run-dir 需要参数}"; shift 2 ;;
    --max-retries) MAX_RETRIES="${2:?--max-retries 需要参数}"; shift 2 ;;
    --task-seconds) TASK_SECONDS="${2:?--task-seconds 需要参数}"; shift 2 ;;
    --max-age)     MAX_AGE="${2:?--max-age 需要参数}"; shift 2 ;;
    --log)         LOG="${2:?--log 需要参数}"; shift 2 ;;
    -h|--help)     usage; exit 0 ;;
    *) echo "未知参数：$1（--help 看用法）" >&2; exit 2 ;;
  esac
done

[[ "$MAX_RETRIES" =~ ^[0-9]+$ ]] || { echo "--max-retries 必须是整数：$MAX_RETRIES" >&2; exit 2; }
[[ "$RUN_DIR" = /* ]] || RUN_DIR="$PWD/$RUN_DIR"
mkdir -p "$(dirname "$LOG")"

failed_gates_of() {  # 从 checker 输出里取失败门禁清单（只解析门禁行格式，不改判定）
  printf '%s\n' "$1" | sed -n 's/^\[GATE\]\[\(G[1-6]\)\] FAIL.*/\1/p' | paste -sd, -
}

record() {  # $1=attempt $2=mode $3=maker_exit $4=checker_exit $5=failed_gates $6=note
  ATTEMPT="$1" MODE="$2" MRC="$3" CRC="$4" FAILED="$5" NOTE="$6" LOGF="$LOG" \
  python3 - <<'PY'
import json, os, sys
from datetime import datetime, timezone
rec = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
       "attempt": int(os.environ["ATTEMPT"]), "mode": os.environ["MODE"],
       "maker_exit": int(os.environ["MRC"]), "checker_exit": int(os.environ["CRC"]),
       "failed_gates": [g for g in os.environ["FAILED"].split(",") if g],
       "note": os.environ["NOTE"]}
with open(os.environ["LOGF"], "a", encoding="utf-8") as f:
    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
PY
}

escalate() {  # $1=checker_exit $2=note $3=checker 输出
  local code="$1" note="$2" out="$3"
  local failed; failed="$(failed_gates_of "$out")"
  echo
  echo "=================================================================="
  echo "GATE: 升级人工 — $note"
  echo "  run 目录      : $RUN_DIR"
  echo "  checker 退出码: $code（0=PASS 1=FAIL 3=无法判定）"
  echo "  失败门禁      : ${failed:-（无门禁行，见下面原始输出）}"
  echo "  最后一次判定原文："
  printf '%s\n' "$out" | sed 's/^/      /'
  echo "  审计记录      : $LOG（本批共 $attempt 次判定）"
  echo "  门禁不做修复（DOD §2）。交给人判断的具体问题："
  printf '%s\n' "$out" | sed -n 's/^\[GATE\]\[\(G[1-6]\)\] FAIL: /\1: /p' | sed 's/^/      - /'
  echo "      G1 覆盖 / G2 历史坏 → 这批工作的历史不可信：决定从哪个 run_id 之后作废重跑"
  echo "      G3 三方不一致 / G4 套件指纹对不上 → 只有人有权改 maker/suite.tsv，maker 无权"
  echo "      G5 陈旧或产物时间越界 / G6 环境指纹对不上 → 换机器或重跑，别搬旧 run 目录"
  echo "=================================================================="
  exit 2
}

echo "[gate] run-dir=$RUN_DIR  max-retries=$MAX_RETRIES  task-seconds=$TASK_SECONDS  max-age=$MAX_AGE"
echo "[gate] 审计记录=$LOG"

attempt=0
mode="fresh"
while :; do
  attempt=$((attempt + 1))
  echo
  echo "---- [gate] 第 $attempt 次尝试（maker mode=$mode）----"

  maker_args=(--task-seconds "$TASK_SECONDS")
  [[ "$mode" = "resume" ]] && maker_args+=(--resume)
  maker_out="$(DAY2_RUN_DIR="$RUN_DIR" python3 "$MAKER" "${maker_args[@]}" 2>&1)"
  maker_rc=$?
  echo "     maker 退出码=$maker_rc（仅诊断，不参与判定）"
  printf '%s\n' "$maker_out" | sed -n 's/^/     [maker] /p'

  checker_out="$(python3 "$CHECKER" --run-dir "$RUN_DIR" --max-age "$MAX_AGE" 2>&1)"
  checker_rc=$?
  printf '%s\n' "$checker_out" | sed -n 's/^/     /p'
  failed="$(failed_gates_of "$checker_out")"
  case "$checker_rc" in 0) note=pass ;; 3) note=unjudgeable ;; *) note=fail ;; esac
  record "$attempt" "$mode" "$maker_rc" "$checker_rc" "$failed" "$note"

  if [[ $checker_rc = 0 ]]; then
    echo
    echo "GATE: 通过（第 $attempt 次尝试，checker 判 $checker_rc）"
    exit 0
  fi
  if [[ $checker_rc = 3 ]]; then
    escalate 3 "checker 无法判定：判定对象或权威历史拿不到，maker 重跑修不了（不重试）" "$checker_out"
  fi
  if [[ $attempt -gt $MAX_RETRIES ]]; then
    escalate 1 "连续 $attempt 次判定都是 FAIL（重试上限 $MAX_RETRIES 已用完）" "$checker_out"
  fi
  echo "     判定 FAIL → 重试 $attempt/$MAX_RETRIES（mode=resume：让恢复接盘未闭合的 run）"
  mode="resume"
done
