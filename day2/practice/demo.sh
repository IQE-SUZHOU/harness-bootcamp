#!/usr/bin/env bash
# Day 2 demo：跑到一半 kill -9，再恢复。
#
# 用法：
#   ./demo.sh                       # 默认在 task-05（stream 型副作用）中途下刀
#   ./demo.sh task-04              # 换下刀位置（atomic 型副作用，对比用）
#   TASK_SECONDS=0.2 ./demo.sh     # 调快慢
#
# 关键点：下刀时机不是 sleep 猜出来的，而是轮询 journal 等到
# 目标任务的 task_started 出现后再等一小段（落在任务中段），
# 因此机器快慢都能稳定复现"任务被中断在半路"。
#
# 注意：这里不用 `set -e` —— kill / wait 对被杀进程必然返回非 0。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="${DAY2_RUN_DIR:-$ROOT/run}"
STATE="$RUN_DIR/state.json"
JOURNAL="$RUN_DIR/events.jsonl"
ART_DIR="$RUN_DIR/artifacts"
KILL_AT="${1:-task-05}"
TASK_SECONDS="${TASK_SECONDS:-0.6}"   # weight=1.0 任务的模拟耗时
BITE_DELAY="${BITE_DELAY:-0.4}"       # 看到 task_started 后多久下手
RESUME_SECONDS="${RESUME_SECONDS:-0.3}"

hr()  { printf '\n=== %s ===\n' "$1"; }
die() { printf 'DEMO FAILED: %s\n' "$1" >&2; exit 1; }

show_state() {
  python3 - "$STATE" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
print(f"  status={d['status']} mode={d['mode']} gen={d['generation']} "
      f"run_id={d['run_id']} journal.last_seq={d['journal']['last_seq']}")
for t in d["tasks"].values():
    print(f"  {t['id']} {t['name']:<15} {t['status']:<8} attempt={t['attempt']} "
          f"digest={t['result_digest']}")
PY
}

show_journal() {
  printf '  总行数=%s  task_started=%s  task_finished=%s\n' \
    "$(wc -l < "$JOURNAL")" \
    "$(grep -cF '"event": "task_started"' "$JOURNAL")" \
    "$(grep -cF '"event": "task_finished"' "$JOURNAL")"
  printf '  尾部 4 行：\n'
  tail -n 4 "$JOURNAL" | sed 's/^/    /'
}

show_artifacts() {
  for f in "$ART_DIR"/*.txt; do
    [ -e "$f" ] || continue
    printf '  %-12s %-8s 行数=%-3s mtime=%s md5=%s\n' \
      "$(basename "$f" .txt)" "artifact" \
      "$(wc -l < "$f")" \
      "$(date -d "@$(stat -c %Y "$f")" +%H:%M:%S)" \
      "$(md5sum < "$f" | cut -c1-8)"
  done
}

snapshot_manifest() {  # 记下每个产物的 mtime/md5，恢复后用来证明"skip 真的没重做"
  : > "$1"
  for f in "$ART_DIR"/*.txt; do
    [ -e "$f" ] || continue
    printf '%s\t%s\t%s\n' "$(basename "$f" .txt)" "$(stat -c %Y "$f")" \
      "$(md5sum < "$f" | cut -c1-8)" >> "$1"
  done
}

journal_has_started() {
  [ -f "$JOURNAL" ] || return 1
  grep -F '"event": "task_started"' "$JOURNAL" | grep -Fq "\"task_id\": \"$1\""
}

# 轮询 journal 等目标任务开始；进程提前退出或超时都算失败
wait_for_start() {
  local tid="$1" limit="${2:-600}" i=0
  while (( i < limit )); do
    if journal_has_started "$tid"; then return 0; fi
    kill -0 "$PID" 2>/dev/null || die "harness 在 $tid 开始前就退出了"
    sleep 0.05; (( i += 1 ))
  done
  die "等不到 $tid 的 task_started 事件（超时）"
}

# --------------------------------------------------------------------------
hr "0. 清场"
rm -rf "$RUN_DIR"
mkdir -p "$ART_DIR"
printf '  RUN_DIR=%s\n  下刀位置=%s  TASK_SECONDS=%s  BITE_DELAY=%s\n' \
  "$RUN_DIR" "$KILL_AT" "$TASK_SECONDS" "$BITE_DELAY"

hr "1. 启动 harness（gen1）并在 ${KILL_AT} 中途 kill -9"
python3 -u "$ROOT/harness.py" --task-seconds "$TASK_SECONDS" &
PID=$!
printf '  已启动 pid=%s，轮询 journal 等待 %s 的 task_started…\n' "$PID" "$KILL_AT"
wait_for_start "$KILL_AT"
printf '  看到 %s task_started，再等 %ss 让它跑进任务中段\n' "$KILL_AT" "$BITE_DELAY"
sleep "$BITE_DELAY"
kill -9 "$PID"
wait "$PID" 2>/dev/null
printf '  kill -9 已发出（wait 退出码=%s，137 = 128+SIGKILL）\n' "$?"

hr "2. 恢复前现场：快照 / journal / 产物"
show_state
hr "2a. journal 现状"
show_journal
hr "2b. 产物现状（${KILL_AT}：stream 型会留半截，atomic 型要么没有要么完整）"
show_artifacts
BEFORE="$RUN_DIR/.before_resume.tsv"
snapshot_manifest "$BEFORE"

hr "3. 恢复决策：journal 回放对账（--status，只判定不执行）"
python3 -u "$ROOT/harness.py" --status || die "--status 失败"

hr "4. 恢复执行（--resume）"
python3 -u "$ROOT/harness.py" --resume --task-seconds "$RESUME_SECONDS" \
  || die "--resume 失败"

hr "5. 恢复后现场"
show_state
hr "5a. journal 现状"
show_journal
hr "5b. 产物：skip 的任务 mtime 未变，rerun 的任务被重写"
python3 - "$BEFORE" "$ART_DIR" <<'PY'
import hashlib, pathlib, sys, datetime
before = {}
for line in pathlib.Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    tid, mtime, md5 = line.split("\t")
    before[tid] = (int(mtime), md5)
for f in sorted(pathlib.Path(sys.argv[2]).glob("*.txt")):
    tid = f.stem
    after = (int(f.stat().st_mtime), hashlib.md5(f.read_bytes()).hexdigest()[:8])
    old = before.get(tid)
    lines = f.read_text(encoding="utf-8").count("\n")
    if old is None:
        verdict = "新产物（本次首次执行）"
    elif old == after:
        verdict = "未改动 → 证明确实被 SKIP"
    else:
        verdict = f"被重写 → RERUN（md5 {old[1]} -> {after[1]}）"
    print(f"  {tid}  行数={lines:<3} mtime={datetime.datetime.fromtimestamp(after[0]):%H:%M:%S}  {verdict}")
PY
[ "$?" -eq 0 ] || die "产物对比失败"

hr "6. 校验"
python3 - "$STATE" "$JOURNAL" "$KILL_AT" <<'PY'
import json, pathlib, sys
state = json.load(open(sys.argv[1], encoding="utf-8"))
journal = pathlib.Path(sys.argv[2]).read_text(encoding="utf-8").splitlines()
kill_at = sys.argv[3]
tasks = state["tasks"]
bad = [t["id"] for t in tasks.values() if t["status"] != "done"]
assert not bad, f"仍有未完成任务: {bad}"
assert state["status"] == "completed", state["status"]

started = sum(1 for l in journal if '"event": "task_started"' in l)
finished = sum(1 for l in journal if '"event": "task_finished"' in l)
seqs = [json.loads(l)["seq"] for l in journal]
assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs), "journal seq 不单调/不唯一"

target = tasks[kill_at]
assert target["attempt"] == 2, f"{kill_at} attempt={target['attempt']}，应为 2"
print(f"  OK 8/8 done；journal {len(journal)} 行 seq 连续单调")
print(f"  OK 全程 task_started={started} 次 vs task_finished={finished} 次 "
      f"→ 差 {started - finished} 次，正是被 kill 的那一次尝试没有闭合")
print(f"  OK {kill_at} attempt=2（重跑），其 digest={target['result_digest']}（与首次一致 → 幂等）")
runs = [json.loads(l) for l in journal if '"event": "run_started"' in l]
run_fin = sum(1 for l in journal if '"event": "run_finished"' in l)
assert [r["mode"] for r in runs] == ["fresh", "resume"], [r["mode"] for r in runs]
assert len(runs) - run_fin == 1, "run_started 与 run_finished 之差应为 1（被杀的进程没有闭合）"
gens = sorted({json.loads(l)["generation"] for l in journal if '"event": "run_finished"' in l})
print(f"  OK 进程代数：run_started={len(runs)} 次 modes={[r['mode'] for r in runs]}；"
      f"run_finished 只出现在 generations={gens}（gen1 被杀，没有 run_finished）")
PY
[ "$?" -eq 0 ] || die "校验失败"

hr "完成"
printf '  中断→恢复闭环跑通。设计说明见 STATE_DESIGN.md；过程记录见 .agent/HANDOFF.md\n'
