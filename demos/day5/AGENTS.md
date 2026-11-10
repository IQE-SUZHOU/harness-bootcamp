# D5 Super-agent Workspace

D5 nested instructions marker: D5-NESTED-AGENTS-V1

## Mission

Build and verify the WCF super-agent integration artifact for D1–D5. This
workspace is the Lead's instruction scope for the D5 demo: it sits below the
repository root, so both the repository `AGENTS.md` and this file are injected.

Load the `d5-super-agent` skill before any D5 assessment work. The skill owns
the assessment-log contract; this file owns the local guardrails.

## Evidence rules

- Every task completion needs a session seq, task revision, or file path.
- Use the Team board for ownership; read the latest revision before every
  update. Stale revisions must be reported, never retried.
- The independent verifier looks only at executable evidence. Do not claim
  PASS from a maker's self-report.
- Do not modify `flow/workflow.js`, `flow/limits.yml`, or `prompts/` during a
  run. They are the fixed experiment inputs.

## Write scope

- Write generated output only under `../../d5-artifacts/`.
- The demo's only external write is `dsh` session state under
  `$DSH_HOME/sessions/`, which is the runtime's persistence store.
- Never write secrets, tokens, or machine-local paths into artifacts.

## Team protocol

- One task per workstream: `harness-foundation`, `state-context`,
  `verification`, `loop-graph`, plus `integration` and `cas-proof`.
- The Lead creates the board, the `cas-proof` task, and the final integration
  task. Teammates may claim unowned tasks.
- Complete or release every task you own. The board never releases owners
  automatically.
- Report owners by the names shown by `list_agents`.

## Output contract

- The assessment log is generated deterministically by the demo from
  `team/task`, `team/member`, and session events; the Lead verifies the board
  instead of writing a self-report.
- The final answer is a six-line teach-back: Harness, State, Context,
  Verification, Loop, Graph — each with a concrete evidence reference.
