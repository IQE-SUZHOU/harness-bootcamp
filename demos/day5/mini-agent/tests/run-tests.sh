#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MINI_AGENT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# The mini-agent has no npm dependencies and no build step: Node runs the
# TypeScript sources directly through type stripping. Node 23.6+ supports the
# flag without the warning, so the flag is kept for the Node 22 floor.
NODE_FLAGS=(--experimental-strip-types --no-warnings=ExperimentalWarning)

if ! node --version >/dev/null 2>&1; then
  echo "mini-agent tests: node is required" >&2
  exit 1
fi

cd "$MINI_AGENT_DIR"
exec node "${NODE_FLAGS[@]}" --test tests/*.test.ts
