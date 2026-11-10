#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ARTIFACTS="${D5_ARTIFACTS:-$ROOT/d5-artifacts}"
RUNS="$ARTIFACTS/runs"
EVIDENCE="$SCRIPT_DIR/evidence"
PROMPTS="$SCRIPT_DIR/prompts"
TEAM_PATCH="$SCRIPT_DIR/team-patch.yml"
LIMITS="$SCRIPT_DIR/flow/limits.yml"
DSH="${DSH:-dsh}"
DSH_TIMEOUT="${DSH_TIMEOUT:-900}"
DSH_PATCH="${DSH_PATCH:-}"
SESSIONS_ROOT="${DSH_HOME:-$HOME/.dsh}/sessions"
FAILURES=()

log() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*" >&2; }
fail() { FAILURES+=("$*"); printf 'ACCEPTANCE FAIL: %s\n' "$*" >&2; }

for cmd in "$DSH" zstd python3 timeout; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "required command not found: $cmd" >&2
    exit 1
  fi
done
for required in "$TEAM_PATCH" "$LIMITS" "$SCRIPT_DIR/verify/static.sh" "$SCRIPT_DIR/verify/verify_d5.py"; do
  if [[ ! -e "$required" ]]; then
    echo "required artifact not found: $required" >&2
    exit 1
  fi
done
chmod +x "$SCRIPT_DIR/verify/static.sh" "$SCRIPT_DIR/verify/static_checks.py" "$SCRIPT_DIR/verify/verify_d5.py"

DSH_VERSION="$("$DSH" --version 2>&1 | head -1)"
log "prepare workspace"
rm -rf "$ARTIFACTS"
mkdir -p "$RUNS" "$EVIDENCE"
find "$EVIDENCE" -mindepth 1 -maxdepth 1 ! -name README.md -exec rm -rf {} +

python3 - "$PROMPTS/turn3.txt.in" "$SCRIPT_DIR/flow/workflow.js" "$RUNS/turn3.txt" <<'PY'
import sys
from pathlib import Path

template = Path(sys.argv[1]).read_text(encoding="utf-8")
script = Path(sys.argv[2]).read_text(encoding="utf-8").strip()
Path(sys.argv[3]).write_text(template.replace("@@WORKFLOW_SCRIPT@@", script), encoding="utf-8")
PY

run_turn() {
  local name="$1" prompt="$2" resume="${3:-}"
  local out="$RUNS/$name.ndjson" err="$RUNS/$name.err"
  local args=(--profile headless)
  [[ -n "$DSH_PATCH" ]] && args+=(--patch "$DSH_PATCH")
  args+=(--patch "$TEAM_PATCH" --patch "$LIMITS")
  [[ -n "$resume" ]] && args+=(--session-id "$resume")
  args+=(--json)
  log "dsh turn: $name"
  set +e
  ( cd "$SCRIPT_DIR" && timeout "$DSH_TIMEOUT" "$DSH" "${args[@]}" - ) \
    < "$prompt" > "$out" 2> "$err"
  local rc=$?
  set -e
  if (( rc != 0 )); then
    log "dsh turn '$name' failed rc=$rc"
    tail -20 "$err" >&2 || true
    return 1
  fi
}

log "turn 1: skill + six tasks + seed token"
run_turn turn1 "$PROMPTS/turn1.txt"
ROOT_SID="$(python3 "$SCRIPT_DIR/team_tools.py" session-id "$RUNS/turn1.ndjson")"
if [[ -z "$ROOT_SID" ]]; then
  echo "session id missing after turn1" >&2
  exit 1
fi
printf '%s\n' "$ROOT_SID" > "$RUNS/root.sid"
TURN_SIDS=("turn1=$ROOT_SID")

for turn in turn2 turn3 turn4; do
  log "resume: $turn"
  prompt="$PROMPTS/$turn.txt"
  [[ "$turn" == "turn3" ]] && prompt="$RUNS/turn3.txt"
  run_turn "$turn" "$prompt" "$ROOT_SID"
  sid="$(python3 "$SCRIPT_DIR/team_tools.py" session-id "$RUNS/$turn.ndjson")"
  TURN_SIDS+=("$turn=$sid")
  if [[ "$sid" != "$ROOT_SID" ]]; then
    fail "$turn resumed a different session ($sid != $ROOT_SID)"
  fi
done

KEY="$(python3 "$SCRIPT_DIR/team_tools.py" project-key "$SCRIPT_DIR")"
ROOT_LOG="$SESSIONS_ROOT/$KEY/$ROOT_SID/session.v4.jsonl.zstd"
if [[ ! -f "$ROOT_LOG" ]]; then
  echo "root session log not found: $ROOT_LOG" >&2
  exit 1
fi
zstd -dc "$ROOT_LOG" > "$RUNS/root.events.jsonl"

log "parse root session"
REPLACE=(--replace "$ROOT" "<repo-root>" --replace "${DSH_HOME:-$HOME/.dsh}" "<dsh-home>" --replace "$HOME" "<home>")
python3 "$SCRIPT_DIR/team_tools.py" root "$RUNS/root.events.jsonl" "${REPLACE[@]}" > "$EVIDENCE/root.json"

log "parse child sessions"
python3 - "$EVIDENCE/root.json" > "$RUNS/members.tsv" <<'PY'
import json
import sys

root = json.load(open(sys.argv[1], encoding="utf-8"))
seen = {}
for member in root.get("teamMembers") or []:
    member_id = member.get("id")
    if member_id and member_id not in seen:
        seen[member_id] = member.get("name") or member_id
for member_id, name in seen.items():
    print(f"{name}\t{member_id}")
PY

CHILD_JSONS=()
while IFS=$'\t' read -r name child_id; do
  [[ -z "$name" ]] && continue
  child_log="$SESSIONS_ROOT/$KEY/$child_id/session.v4.jsonl.zstd"
  if [[ ! -f "$child_log" ]]; then
    fail "child log missing for $name ($child_id)"
    continue
  fi
  zstd -dc "$child_log" > "$RUNS/child-$name.events.jsonl"
  python3 "$SCRIPT_DIR/team_tools.py" child "$RUNS/child-$name.events.jsonl" --name "$name" "${REPLACE[@]}" \
    > "$RUNS/child-$name.json"
  CHILD_JSONS+=("$RUNS/child-$name.json")
done < "$RUNS/members.tsv"

python3 - "${CHILD_JSONS[@]}" > "$EVIDENCE/children.json" <<'PY'
import json
import sys

children = [json.load(open(path, encoding="utf-8")) for path in sys.argv[1:]]
children.sort(key=lambda child: child.get("name") or "")
print(json.dumps(children, ensure_ascii=False, indent=2))
PY

log "collect effective config"
config_args=(--profile headless)
[[ -n "$DSH_PATCH" ]] && config_args+=(--patch "$DSH_PATCH")
config_args+=(--patch "$TEAM_PATCH" --patch "$LIMITS")
if "$DSH" "${config_args[@]}" --dump-config > "$RUNS/effective-config.yml" 2> "$RUNS/effective-config.err"; then
  python3 "$SCRIPT_DIR/team_tools.py" effective-config "$RUNS/effective-config.yml" > "$EVIDENCE/stop-condition.json"
  python3 "$SCRIPT_DIR/team_tools.py" goal-config "$RUNS/effective-config.yml" > "$EVIDENCE/auto-loop.json"
else
  fail "unable to dump effective config"
  printf '{}\n' > "$EVIDENCE/stop-condition.json"
  printf '{}\n' > "$EVIDENCE/auto-loop.json"
fi

log "write environment summary"
python3 - "$ARTIFACTS/env.json" "$DSH_VERSION" "$ROOT_SID" "${TURN_SIDS[@]}" <<'PY'
import json
import sys
from datetime import datetime, timezone

path, dsh_version, root_sid, *turns = sys.argv[1:]
sessions = {}
for item in turns:
    name, _, session_id = item.partition("=")
    sessions[name] = session_id
payload = {
    "dshVersion": dsh_version,
    "rootSession": root_sid,
    "turnSessions": sessions,
    "cwd": "<repo-root>/demos/day5",
    "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    "patches": ["team-patch.yml", "flow/limits.yml"],
    "modelOverlay": bool(__import__("os").environ.get("DSH_PATCH")),
}
open(path, "w", encoding="utf-8").write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
PY

log "render evidence"
if ! python3 "$SCRIPT_DIR/render_evidence.py" --evidence-dir "$EVIDENCE" --env "$ARTIFACTS/env.json"; then
  fail "evidence rendering reported a failed check"
fi

log "verify evidence"
if ! python3 "$SCRIPT_DIR/verify/verify_d5.py" --evidence-dir "$EVIDENCE" --output "$EVIDENCE/verifier-result.json"; then
  fail "non-LLM verifier rejected the evidence"
fi

log "done"

if (( ${#FAILURES[@]} > 0 )); then
  printf '\nfailures:\n' >&2
  printf '  %s\n' "${FAILURES[@]}" >&2
  exit 1
fi

python3 - "$EVIDENCE/summary.json" <<'PY'
import json
import sys

summary = json.load(open(sys.argv[1], encoding="utf-8"))
print("\nacceptance:")
for name, passed in summary["acceptance"].items():
    print(f"  {'PASS' if passed else 'FAIL'}  {name}")
print(f"\nevidence: {sys.argv[1].rsplit('/', 1)[0]}")
PY
