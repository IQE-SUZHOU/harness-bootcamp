#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
answer="$(tr -d '[:space:]' < "$root/src/answer.txt")"

if [[ ! "$answer" =~ ^[0-9]+$ ]]; then
  echo "FAIL: answer is not numeric: $answer" >&2
  exit 1
fi

echo "BENCH=$((answer * 235 + 6))"
