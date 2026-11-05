#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
test -f "$repo_root/AGENTS.md"
test -x "$repo_root/scripts/check.sh"
echo "practice repo ok: $repo_root"
