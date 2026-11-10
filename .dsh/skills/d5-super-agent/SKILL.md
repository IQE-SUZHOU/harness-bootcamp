---
name: d5-super-agent
description: Integration checklist for the WCF D5 super-agent assessment; load before running or reporting the D1-D4 integration.
whenToUse: Use when the task mentions D5, super-agent, integration assessment, or the WCF harness bootcamp teach-back.
metadata:
  version: 1
---

# D5 Super-agent Integration

Marker: `D5-SUPER-AGENT-SKILL-V1`

## Mandatory checks

1. **Harness (D1)** — AGENTS.md is injected as a `user/message` whose `source.kind` is `agent-instructions`; the profile is `headless`; tools come from mounted plugins, not a privileged core.
2. **State (D2)** — one durable `session.v4.jsonl.zstd` holds every turn; resume appends to the same log instead of rewriting it.
3. **Context (D3)** — fork inherits the Lead's completed turns; fresh spawn starts empty; neither inherits the Lead's permissions.
4. **Verification (D3)** — DoD items must be decidable. The independent verifier looks only at executable evidence, never at a maker's self-report.
5. **Loop (D4)** — the goal round cap is the auto-loop exit condition; workflow stop conditions bound every run.
6. **Graph (D4)** — `parallel()` has no cross-item barrier; fan-in starts only after every branch ends; a branch failure becomes `null`, while fatal errors abort the whole run.

## Team task board

- Create one task per workstream: `harness-foundation`, `state-context`, `verification`, `loop-graph`.
- Add an `integration` task blocked by all four.
- Claim only with the latest revision. Every update is compare-and-set; a stale revision is a failure, never a silent retry.
- Complete or release every task you own. The board never releases owners automatically.
- Report owners explicitly: `lead`, a teammate name, or a session id with a recorded name.

## Assessment log contract

The assessment log must be reproducible from the session log and the Team task board. If the task names a path, write it there; otherwise report the sections in your final message. It must contain:

- the heading `# D5 Assessment Log - WCF`;
- a task table: `Task | Owner | Status | Evidence`;
- a six-line teach-back table: `Line | One-sentence claim | Evidence`;
- an acceptance table: `Item | Result | Evidence`.

Never claim PASS without a session seq, task revision, or file path.

## Failure rules

- A stale task revision must be reported as a CAS failure, never retried silently.
- A fresh teammate that cannot see the Lead's token must answer `UNKNOWN`.
- A failed workflow branch is `null`; never count it as a success.
