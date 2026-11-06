#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"

out="${D2_OUT_DIR:-$repo_root/d2-artifacts}"
mkdir -p "$out"

for cmd in dsh zstd python3; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "missing command: $cmd" >&2; exit 1; }
done

key="$(python3 demos/day2/projectkey.py "$repo_root")"
echo "repo = $repo_root"
echo "out  = $out"
echo "key  = $key"
echo "dsh  = $(dsh --version)"

extract_session_id() {
  python3 - "$1" <<'PY'
import json
import sys

for line in open(sys.argv[1], encoding="utf-8"):
    line = line.strip()
    if not line:
        continue
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        continue
    if event.get("type") == "session":
        print(event.get("sessionId", ""))
        break
PY
}

extract_final() {
  python3 - "$1" <<'PY'
import json
import sys

text = ""
for line in open(sys.argv[1], encoding="utf-8"):
    line = line.strip()
    if not line:
        continue
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        continue
    if event.get("type") == "final":
        text = event.get("text", "")
print(text)
PY
}

max_cache_read() {
  python3 - "$1" <<'PY'
import json
import sys

values = []
for line in open(sys.argv[1], encoding="utf-8"):
    line = line.strip()
    if not line:
        continue
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        continue
    usage = event.get("usage")
    if isinstance(usage, dict):
        values.append(int(usage.get("cacheReadTokens", 0)))
print(max(values) if values else 0)
PY
}

echo
echo "== 1/7 normal run =="
dsh --profile headless --json "用一句话回答：1+1等于几？" > "$out/run1.ndjson"
sid1="$(extract_session_id "$out/run1.ndjson")"
if [ -z "$sid1" ]; then
  echo "failed to read session id from $out/run1.ndjson" >&2
  exit 1
fi
dir1="$HOME/.dsh/sessions/$key/$sid1"
test -f "$dir1/session.v4.jsonl.zstd"
echo "sessionId = $sid1"

echo
echo "== 2/7 inspect session files =="
ls -la "$dir1" | tee "$out/session-files.txt"
zstd -dc "$dir1/session.v4.jsonl.zstd" > "$out/events-turn1.jsonl"
python3 demos/day2/analyze_session.py "$out/events-turn1.jsonl" --timeline > "$out/timeline-turn1.txt"
python3 demos/day2/analyze_session.py "$out/events-turn1.jsonl" --json > "$out/summary-turn1.json"

echo
echo "== 3/7 normal resume =="
dsh --profile headless --json --session-id "$sid1" \
  "我刚才问了你 1+1 等于几？现在再问一次，并说说之前聊过什么" > "$out/resume1.ndjson"
zstd -dc "$dir1/session.v4.jsonl.zstd" > "$out/events-after-resume1.jsonl"
python3 demos/day2/analyze_session.py "$out/events-after-resume1.jsonl" --json > "$out/summary-after-resume1.json"
extract_final "$out/resume1.ndjson" > "$out/resume1-final.txt"
cache_read="$(max_cache_read "$out/resume1.ndjson")"
echo "resume cacheReadTokens = $cache_read"

echo
echo "== 4/7 start long task and hard-kill its process group =="
python3 - > "$out/kill.ndjson" 2> "$out/kill.err" <<'PY' &
import os

os.setsid()
os.execvp(
    "dsh",
    ["dsh", "--profile", "headless", "--json", "请运行 bash: sleep 300 && echo done"],
)
PY
kill_pid=$!

for _ in $(seq 1 60); do
  if grep -q '"type":"session"' "$out/kill.ndjson" 2>/dev/null; then
    break
  fi
  sleep 0.5
done
sid2="$(extract_session_id "$out/kill.ndjson")"
if [ -z "$sid2" ]; then
  echo "failed to read session id from long-running task" >&2
  kill -9 -"$kill_pid" 2>/dev/null || true
  exit 1
fi
dir2="$HOME/.dsh/sessions/$key/$sid2"
echo "sessionId = $sid2"

open_call() {
  zstd -dc "$dir2/session.v4.jsonl.zstd" 2>/dev/null | python3 -c '
import json
import sys

calls, results = {}, set()
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        continue
    data = event.get("data", {}) or {}
    if event.get("type") == "tool/call":
        calls[data.get("callId")] = data.get("name")
    elif event.get("type") == "tool/result":
        message = data.get("message", {}) or {}
        results.add(message.get("toolCallId") or (message.get("source") or {}).get("callId"))
pending = {k: v for k, v in calls.items() if k not in results}
if pending:
    call_id, name = next(iter(pending.items()))
    print(f"{call_id} {name}")
' 2>/dev/null || true
}

pending=""
for _ in $(seq 1 120); do
  current="$(open_call)"
  if [ -n "$current" ] && [ "$current" = "$pending" ]; then
    break
  fi
  pending="$current"
  sleep 1
done
if [ -z "$pending" ]; then
  echo "did not observe a stable open tool call; killing anyway" >&2
else
  echo "open tool call at kill time: $pending"
fi
kill -9 -"$kill_pid" 2>/dev/null || true
for _ in $(seq 1 20); do
  kill -0 "$kill_pid" 2>/dev/null || break
  sleep 0.2
done
wait "$kill_pid" 2>/dev/null || true
sleep 1
echo "killed process group $kill_pid"

echo
echo "== 5/7 inspect interrupted session =="
zstd -dc "$dir2/session.v4.jsonl.zstd" > "$out/events-interrupted.jsonl" 2>/dev/null || true
python3 demos/day2/analyze_session.py "$out/events-interrupted.jsonl" --timeline > "$out/timeline-interrupted.txt"
python3 demos/day2/analyze_session.py "$out/events-interrupted.jsonl" --json > "$out/interrupted-summary.json"
python3 - "$out/interrupted-summary.json" <<'PY'
import json
import sys

summary = json.load(open(sys.argv[1], encoding="utf-8"))
print(json.dumps({
    "open_turns": summary["open_turns"],
    "open_steps": summary["open_steps"],
    "open_tool_calls": summary["open_tool_calls"],
}, ensure_ascii=False, indent=2))
if not summary["open_turns"] or not summary["open_steps"] or not summary["open_tool_calls"]:
    raise SystemExit("did not reproduce an interrupted turn (try increasing the wait)")
PY

echo
echo "== 6/7 resume after crash =="
dsh --profile headless --json --session-id "$sid2" "继续" > "$out/resume2.ndjson"
zstd -dc "$dir2/session.v4.jsonl.zstd" > "$out/events-after-resume2.jsonl"
python3 demos/day2/analyze_session.py "$out/events-after-resume2.jsonl" --timeline > "$out/timeline-after-resume2.txt"
python3 demos/day2/analyze_session.py "$out/events-after-resume2.jsonl" --json > "$out/after-resume2-summary.json"
extract_final "$out/resume2.ndjson" > "$out/resume2-final.txt"

echo
echo "== 7/7 verify crash repair =="
python3 - "$out" "$repo_root" "$key" "$sid1" "$sid2" "$cache_read" <<'PY'
import json
import subprocess
import sys

out, repo_root, key, sid1, sid2, cache_read = sys.argv[1:7]
turn1 = json.load(open(f"{out}/summary-turn1.json", encoding="utf-8"))
after1 = json.load(open(f"{out}/summary-after-resume1.json", encoding="utf-8"))
interrupted = json.load(open(f"{out}/interrupted-summary.json", encoding="utf-8"))
after2 = json.load(open(f"{out}/after-resume2-summary.json", encoding="utf-8"))

checks = {
    "session_file_created": True,
    "event_log_readable": turn1["events"] > 0 and turn1["last_seq"] is not None,
    "normal_resume_lossless": "1+1" in open(f"{out}/resume1-final.txt", encoding="utf-8").read(),
    "kv_cache_reused": int(cache_read) > 0,
    "baseline_injected_once": turn1["baseline_instruction_occurrences"] == 1,
    "interrupted_turn_visible": bool(interrupted["open_turns"]),
    "interrupted_step_visible": bool(interrupted["open_steps"]),
    "interrupted_tool_call_visible": bool(interrupted["open_tool_calls"]),
    "interrupted_tool_result_closer": bool(after2["interrupted_tool_results"]),
    "interrupted_turn_end_closer": bool(after2["interrupted_turn_ends"]),
    "open_turns_closed": not after2["open_turns"],
    "open_steps_closed": not after2["open_steps"],
    "baseline_still_once": after2["baseline_instruction_occurrences"] == 1,
}

summary = {
    "repo": repo_root,
    "dsh_version": subprocess.check_output(["dsh", "--version"], text=True).strip(),
    "project_key": key,
    "normal_session": {
        "session_id": sid1,
        "events": turn1["events"],
        "last_seq": turn1["last_seq"],
        "baseline_instruction_occurrences": turn1["baseline_instruction_occurrences"],
        "resume_cache_read_tokens": int(cache_read),
        "resume_events": after1["events"],
    },
    "interrupted_session": {
        "session_id": sid2,
        "last_seq_before_resume": interrupted["last_seq"],
        "open_turns": interrupted["open_turns"],
        "open_steps": interrupted["open_steps"],
        "open_tool_calls": interrupted["open_tool_calls"],
    },
    "after_resume": {
        "interrupted_tool_results": after2["interrupted_tool_results"],
        "interrupted_turn_ends": after2["interrupted_turn_ends"],
        "open_turns": after2["open_turns"],
        "open_steps": after2["open_steps"],
        "baseline_instruction_occurrences": after2["baseline_instruction_occurrences"],
    },
    "checks": checks,
}
with open(f"{out}/summary.json", "w", encoding="utf-8") as handle:
    json.dump(summary, handle, ensure_ascii=False, indent=2)

passed = all(checks.values())
lines = [
    "# D2 interrupt → resume evidence",
    "",
    f"- repo: `{repo_root}`",
    f"- dsh: `{summary['dsh_version']}`",
    f"- project key: `{key}`",
    f"- normal session: `{sid1}`",
    f"- interrupted session: `{sid2}`",
    f"- resume cacheReadTokens: `{cache_read}`",
    "",
    "| check | result |",
    "| --- | --- |",
]
for name, value in checks.items():
    lines.append(f"| {name} | {'PASS' if value else 'FAIL'} |")
with open(f"{out}/evidence.md", "w", encoding="utf-8") as handle:
    handle.write("\n".join(lines) + "\n")

print(json.dumps(checks, ensure_ascii=False, indent=2))
if not passed:
    raise SystemExit("one or more checks failed")
print(f"\nall checks passed; evidence in {out}")
PY
