#!/usr/bin/env bash
# gate_selftest.sh — 验证 gate.sh 的四条路径（T5 的验收），全在 .gate_selftest/ 的 scratch
# run 目录上跑，不动 lab 的 run/、不改 checker.py、不改 maker/。
#
#   A 合法现场（空目录起步，maker 自己跑完）      → checker PASS → gate.sh exit 0（不误杀）
#   B 合法现场 + journal 被撕出半截行             → 自动重试修不好历史 → 用尽 3 次重试 → exit 2
#   C 连判定对象都拿不到（run 目录是个普通文件）  → checker 退出码 3 → 不重试，直接 exit 2
#   D maker 被 kill -9 打断                        → fresh 修不好 → resume 接盘 → exit 0
set -uo pipefail
LAB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
S="$LAB/.gate_selftest"
rm -rf "$S"; mkdir -p "$S"
bad=0

# 全程输出先进文件（落盘规则），结束时再回放到终端并写 GATE_RESULTS.md
log="$(mktemp)"; trap 'rm -f "$log"' EXIT
exec 3>&1
exec >"$log" 2>&1

check() {  # $1=名字 $2=期望 $3=实得
  if [[ "$2" = "$3" ]]; then echo "✓ $1：期望 $2，实得 $3"
  else echo "✗ $1：期望 $2，实得 $3"; bad=$((bad + 1)); fi
}

# ---------- A 合法现场 ----------
echo "=== A 合法现场 → gate.sh 应 exit 0 ==="
mkdir -p "$S/A/run"
outA="$(bash "$LAB/gate.sh" --run-dir "$S/A/run" --log "$S/A.jsonl" --task-seconds 0.02 2>&1)"; rcA=$?
printf '%s\n' "$outA" | tail -12
check "A gate.sh 退出码" "0" "$rcA"
grep -q "GATE: 通过" <<<"$outA" || { echo "✗ A 没有『GATE: 通过』"; bad=$((bad+1)); }
grep -q "GATE: PASS (6/6 passed)" <<<"$outA" || { echo "✗ A 的 checker 不是 6/6"; bad=$((bad+1)); }

# ---------- B 历史坏掉（自动重试修不好） ----------
echo
echo "=== B journal 半截行 → gate.sh 应用尽 3 次重试后 exit 2 ==="
mkdir -p "$S/B/run"
DAY2_RUN_DIR="$S/B/run" python3 "$LAB/maker/gpu_harness.py" --task-seconds 0.02 >/dev/null
python3 - "$S/B/run/events.jsonl" <<'PY'
import json, sys
p = sys.argv[1]
lines = [l for l in open(p, encoding="utf-8").read().splitlines() if l.strip()]
last_seq = max(json.loads(l).get("seq", 0) for l in lines)
ts = json.loads(lines[-1])["ts"]
with open(p, "a", encoding="utf-8") as f:      # 追加一半就断——真实 crash 留下的样子
    f.write('{"seq": %d, "ts": "%s", "event": "task_fin' % (last_seq + 1, ts))
PY
echo "   journal 尾部：$(tail -c 90 "$S/B/run/events.jsonl")"
outB="$(bash "$LAB/gate.sh" --run-dir "$S/B/run" --log "$S/B.jsonl" --task-seconds 0.02 2>&1)"; rcB=$?
printf '%s\n' "$outB" | grep -E '^\s*(----|     \[GATE\]|     GATE:|GATE:|     判定 FAIL)' | sed -n '1,40p'
check "B gate.sh 退出码" "2" "$rcB"
grep -q "GATE: 升级人工" <<<"$outB" || { echo "✗ B 没有升级人工块"; bad=$((bad+1)); }
python3 - "$S/B.jsonl" <<'PY'
import json, sys
recs = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8")]
print(f"   审计记录 {len(recs)} 条：" + " ".join(f"#{r['attempt']}/{r['mode']}/checker={r['checker_exit']}/failed={','.join(r['failed_gates']) or '-'}" for r in recs))
assert len(recs) == 4, f"期望 1 次原始 + 3 次重试 = 4 条，实得 {len(recs)}"
assert [r["mode"] for r in recs] == ["fresh", "resume", "resume", "resume"], [r["mode"] for r in recs]
assert all(r["checker_exit"] == 1 and "G2" in r["failed_gates"] for r in recs), recs
print("   ✓ 4 次判定全部 FAIL 且失败的是 G2（坏行留在历史里，maker 重跑修不掉）")
PY
[[ $? = 0 ]] || bad=$((bad + 1))

# ---------- C 无法判定 ----------
echo
echo "=== C run 目录是普通文件（checker 退出码 3）→ gate.sh 应直接 exit 2，不重试 ==="
mkdir -p "$S/C"; : > "$S/C/run"          # run 是个文件不是目录
outC="$(bash "$LAB/gate.sh" --run-dir "$S/C/run" --log "$S/C.jsonl" --task-seconds 0.02 2>&1)"; rcC=$?
printf '%s\n' "$outC" | grep -E '^(GATE:|     GATE:)|无法判定' | head -6
check "C gate.sh 退出码" "2" "$rcC"
grep -q "GATE: 无法判定" <<<"$outC" || { echo "✗ C 里 checker 没报无法判定"; bad=$((bad+1)); }
n="$(wc -l < "$S/C.jsonl" | tr -d ' ')"
check "C 不重试（审计记录条数）" "1" "$n"

# ---------- D 真中断：kill -9 → fresh 修不好 → resume 接盘 ----------
echo
echo "=== D maker 被 kill -9 打断 → gate.sh 应靠 resume 接盘，最终 exit 0（不误杀合法恢复） ==="
mkdir -p "$S/D/run"
DAY2_RUN_DIR="$S/D/run" python3 "$LAB/maker/gpu_harness.py" --task-seconds 0.9 >/dev/null 2>&1 &
killed=$!
sleep 1.4; kill -9 "$killed" 2>/dev/null; wait "$killed" 2>/dev/null
echo "   kill -9 打在 pid=$killed；journal 行数=$(wc -l < "$S/D/run/events.jsonl" | tr -d ' ')，最后事件=$(tail -1 "$S/D/run/events.jsonl" | cut -c1-70)"
outD="$(bash "$LAB/gate.sh" --run-dir "$S/D/run" --log "$S/D.jsonl" --task-seconds 0.02 2>&1)"; rcD=$?
printf '%s\n' "$outD" | grep -E '^\s*(----|     GATE:|GATE:|     判定 FAIL|     \[GATE\]\[G[12]\] FAIL)' | head -20
check "D gate.sh 退出码" "0" "$rcD"
python3 - "$S/D.jsonl" <<'PY'
import json, sys
recs = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8")]
print(f"   审计记录 {len(recs)} 条：" + " ".join(f"#{r['attempt']}/{r['mode']}/checker={r['checker_exit']}/failed={','.join(r['failed_gates']) or '-'}" for r in recs))
assert [r["mode"] for r in recs] == ["fresh", "resume"], [r["mode"] for r in recs]
assert recs[0]["failed_gates"] and recs[1]["failed_gates"] == [] and recs[1]["checker_exit"] == 0, recs
print("   ✓ 第 1 次 fresh 修不好（未闭合的 run 没人接盘 → G2 FAIL），第 2 次 resume 接盘后 6/6 PASS")
PY
[[ $? = 0 ]] || bad=$((bad + 1))

if [[ $bad = 0 ]]; then verdict="gate.sh 四条路径都符合契约。"; rc=0
else verdict="gate.sh 有 $bad 处不符合契约。"; rc=1; fi

exec >&3 2>&1 3>&-            # 恢复终端输出
{
  echo "# GATE_RESULTS.md — gate.sh 四条路径的实跑记录（T5 验收）"
  echo
  echo "- 生成：\`bash gate_selftest.sh\`（$(date -u +%FT%TZ)）"
  echo "- scratch 只在 \`.gate_selftest/\`（A/B/C/D 四个 run 目录 + 每次判定的审计 jsonl）；"
  echo "  未改 \`checker.py\` / \`maker/\` / \`maker/suite.tsv\`，也没动 lab 的 \`run/\`。"
  echo "- 契约见 DOD §4。"
  echo
  echo '```'
  cat "$log"
  echo '```'
} > "$LAB/GATE_RESULTS.md"

echo "$verdict"
echo "落盘：$LAB/GATE_RESULTS.md"
exit $rc
