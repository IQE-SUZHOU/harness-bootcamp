#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mode="${MODE:-real}"
kill_at="${KILL_AT:-3}"
run_timeout="${RUN_TIMEOUT:-600}"
work="$(mktemp -d)"
srv_pid=""

cleanup() {
  if [[ -n "$srv_pid" ]]; then kill "$srv_pid" 2>/dev/null || true; fi
  rm -rf "$work"
}
trap cleanup EXIT

fail() {
  echo "FAIL e2e: $*" >&2
  exit 1
}

cp "$repo_root/src/harness.py" "$work/harness.py"

if [[ "$mode" == "fake" ]]; then
  port_file="$work/port"
  python3 "$repo_root/tests/fake_llm.py" --port-file "$port_file" & srv_pid=$!
  for _ in $(seq 1 100); do [[ -s "$port_file" ]] && break; sleep 0.05; done
  [[ -s "$port_file" ]] || fail "fake llm did not start"
  export BASE_URL="http://127.0.0.1:$(cat "$port_file")/v1"
  export API_KEY=fake
  export MODEL=fake
elif [[ "$mode" == "real" ]]; then
  cp "$repo_root/src/.env" "$work/.env"
else
  fail "unknown MODE=$mode (use real or fake)"
fi

done_count() {
  python3 - "$work/state.json" <<'PY'
import json
import sys

try:
    print(json.load(open(sys.argv[1]))["done"])
except Exception:
    print(0)
PY
}

python3 "$work/harness.py" >"$work/run1.log" 2>&1 &
pid=$!

killed_at=0
for _ in $(seq 1 2400); do
  killed_at="$(done_count)"
  if [[ "$killed_at" -ge "$kill_at" ]]; then break; fi
  kill -0 "$pid" 2>/dev/null || break
  sleep 0.05
done

kill -9 "$pid" 2>/dev/null || true
wait "$pid" 2>/dev/null || true

if [[ "$killed_at" -lt 1 || "$killed_at" -ge 20 ]]; then
  tail -5 "$work/run1.log" >&2 || true
  fail "run #1 stopped at step $killed_at, expected 1..19"
fi

echo "[e2e] killed run #1 at step $killed_at (mode=$mode)"

if ! timeout "$run_timeout" python3 "$work/harness.py" >"$work/run2.log" 2>&1; then
  tail -20 "$work/run2.log" >&2 || true
  fail "resumed run did not finish within ${run_timeout}s"
fi

grep -q '^\[resume\]' "$work/run2.log" || fail "run #2 did not take the resume branch"
python3 "$repo_root/src/verify.py" "$work/state.json" || fail "state invariants broken after resume"

echo "PASS e2e ($mode): killed at step $killed_at, resumed to 20/20, no duplicate or missing steps"
