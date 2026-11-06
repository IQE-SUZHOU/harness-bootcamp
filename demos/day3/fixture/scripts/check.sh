#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
expected="$(tr -d '[:space:]' < "$root/src/expected.txt")"
actual="$(tr -d '[:space:]' < "$root/src/answer.txt")"

if [[ "$actual" != "$expected" ]]; then
  echo "FAIL: answer=$actual expected=$expected" >&2
  exit 1
fi

echo "OK: answer=$actual"
