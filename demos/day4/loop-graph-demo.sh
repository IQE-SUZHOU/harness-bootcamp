#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PROMPTS="$SCRIPT_DIR/prompts"
ARTIFACTS="$ROOT/d4-artifacts"
WORKSPACE="$ARTIFACTS/workspace"
RUNS="$ARTIFACTS/runs"
EVIDENCE="$SCRIPT_DIR/evidence"
HELPER="$SCRIPT_DIR/workflow_tools.py"
RENDER="$SCRIPT_DIR/render_evidence.py"
VERIFY="$SCRIPT_DIR/verify_d4.py"
STOP_PATCH="${D4_STOP_PATCH:-$SCRIPT_DIR/stop-condition.yml}"
CAP_PATCH="${D4_CAP_PATCH:-$SCRIPT_DIR/stop-condition-cap.yml}"
DSH="${DSH:-dsh}"
DSH_TIMEOUT="${DSH_TIMEOUT:-600}"
DSH_PATCH="${DSH_PATCH:-}"
SESSIONS_ROOT="${DSH_HOME:-$HOME/.dsh}/sessions"
FAILURES=()

log() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*" >&2; }
fail() { FAILURES+=("$*"); printf 'ACCEPTANCE FAIL: %s\n' "$*" >&2; }

for cmd in "$DSH" zstd python3 timeout; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "required command not found: $cmd" >&2
    [[ "$cmd" == "dsh" ]] && echo 'hint: install dsh and ensure it is on PATH' >&2
    exit 1
  fi
done

if [[ ! -f "$STOP_PATCH" ]]; then
  echo "stop-condition overlay not found: $STOP_PATCH" >&2
  exit 1
fi

DSH_VERSION="$("$DSH" --version 2>&1 | head -1)"

log "prepare workspace"
rm -rf "$ARTIFACTS"
mkdir -p "$WORKSPACE" "$RUNS" "$EVIDENCE"
find "$EVIDENCE" -mindepth 1 -maxdepth 1 ! -name README.md -exec rm -rf {} +

run_dsh() {
  local name="$1" extra_patch="${2:-}"
  local out="$RUNS/$name.ndjson" err="$RUNS/$name.err"
  local args=(--profile headless)
  [[ -n "$DSH_PATCH" ]] && args+=(--patch "$DSH_PATCH")
  args+=(--patch "$STOP_PATCH")
  [[ -n "$extra_patch" ]] && args+=(--patch "$extra_patch")
  args+=(--json)
  log "dsh run: $name"
  set +e
  ( cd "$WORKSPACE" && timeout "$DSH_TIMEOUT" "$DSH" "${args[@]}" - ) \
    < "$PROMPTS/$name.txt" > "$out" 2> "$err"
  local rc=$?
  set -e
  if (( rc != 0 )); then
    log "dsh run '$name' failed rc=$rc"
    tail -20 "$err" >&2 || true
    return 1
  fi
  local sid
  if ! sid="$(python3 "$HELPER" session-id "$out")"; then
    fail "session id missing for $name"
    return 1
  fi
  printf '%s\n' "$sid" > "$RUNS/$name.sid"
}

session_log_for() {
  local sid="$1"
  local path
  path="$(ls "$SESSIONS_ROOT"/*/"$sid"/session.v4.jsonl.zstd 2>/dev/null | head -1 || true)"
  [[ -n "$path" ]] && printf '%s\n' "$path"
}

collect_run() {
  local name="$1" meta="$2"
  local sid log_path
  sid="$(cat "$RUNS/$name.sid")"
  if ! python3 "$HELPER" extract-workflow "$RUNS/$name.ndjson" \
      --meta-name "$meta" \
      --replace "$ROOT" "<repo-root>" \
      --replace "${DSH_HOME:-$HOME/.dsh}" "<dsh-home>" \
      --replace "$HOME" "<home>" > "$EVIDENCE/$name.json"; then
    fail "workflow result not found for $name"
  fi
  log_path="$(session_log_for "$sid")"
  if [[ -z "$log_path" ]]; then
    fail "session log not found for $name ($sid)"
    return 1
  fi
  zstd -dc "$log_path" > "$RUNS/$name.events.jsonl"
  python3 "$HELPER" workflow-events "$RUNS/$name.events.jsonl" > "$EVIDENCE/$name.events.json"
  python3 "$HELPER" runtime "$RUNS/$name.events.jsonl" > "$EVIDENCE/$name.runtime.json"
}

log "run: three-way fan-out then fan-in summary"
run_dsh fanout
log "run: ordinary branch failure control"
run_dsh partial
log "run: illegal option / fatal failure control"
run_dsh fatal
log "run: agent cap stop condition"
run_dsh cap "$CAP_PATCH"
log "run: synchronous timeout stop condition"
run_dsh timeout

log "collect workflow results and routing events"
collect_run fanout fanout-fanin
collect_run partial partial-failure
collect_run fatal fatal-failure
collect_run cap agent-cap
collect_run timeout sync-timeout

log "collect effective stop-condition config"
config_args=(--profile headless)
[[ -n "$DSH_PATCH" ]] && config_args+=(--patch "$DSH_PATCH")
config_args+=(--patch "$STOP_PATCH")
if "$DSH" "${config_args[@]}" --dump-config > "$ARTIFACTS/effective-config.yml" 2> "$ARTIFACTS/effective-config.err"; then
  python3 "$HELPER" effective-config "$ARTIFACTS/effective-config.yml" > "$EVIDENCE/stop-condition.json"
  python3 "$HELPER" goal-config "$ARTIFACTS/effective-config.yml" > "$EVIDENCE/auto-loop.json"
else
  fail "unable to dump effective config"
fi

session_args=()
for name in fanout partial fatal cap timeout; do
  session_args+=(--session "$name=$(cat "$RUNS/$name.sid")")
done
python3 "$HELPER" env \
  --events "$RUNS/fanout.events.jsonl" \
  --dsh-version "$DSH_VERSION" \
  "${session_args[@]}" \
  --config "$EVIDENCE/stop-condition.json" > "$EVIDENCE/runtime.json"

log "render evidence"
if ! python3 "$RENDER" --evidence-dir "$EVIDENCE"; then
  fail "evidence rendering failed"
fi

log "verify evidence"
if ! python3 "$VERIFY" --evidence-dir "$EVIDENCE" --output "$EVIDENCE/verifier-result.json"; then
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
