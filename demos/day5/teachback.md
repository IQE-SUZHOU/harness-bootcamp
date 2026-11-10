# D5 Teach-back · Six Main Lines

Each line is a falsifiable claim plus the evidence a reviewer can re-run.
The Lead's final answer must cover all six with a concrete session seq, task
revision, or file path.

| Line | One-sentence claim | Evidence |
| --- | --- | --- |
| Harness | dsh has no privileged core: every capability is a mounted plugin row selected by profile → bundles → patches. | `AGENTS.md` injection is a `user/message` with `source.kind=agent-instructions`; the effective config lists `skill`, `subagent`, `workflow-ptc`, and `goal` as rows. |
| State | Model-visible ⟺ logged: every model-visible input has a session event, so replay and resume rebuild the same state. | One `session.v4.jsonl.zstd` holds four resumed turns; `turn/start` and surface events are appended, never rewritten. |
| Context | Fork inherits the Lead's completed turns; fresh spawn starts empty; neither inherits the Lead's permissions. | Fork child log contains `SA-WCF-D5-7F3A`; fresh child log does not; both have their own tool scope. |
| Verification | DoD items must be decidable; a checker that reads executable evidence catches "claimed done" that a self-report hides. | `verify/static.sh` prints `d5 static checks passed`; `verify/verify_d5.py` re-derives every flag without an LLM. |
| Loop | The goal round cap is the auto-loop exit condition; workflow stop conditions bound every run. | `defaultMaxGoalRounds=20`; `maxTotalAgents=10`, `syncTimeoutMs=3000`, `maxConcurrentAgents=2` in the effective config. |
| Graph | `parallel()` has no cross-item barrier; fan-in waits for every branch; a branch failure is `null`, a fatal error aborts the run. | `summary.startSeq` is after all branch `endSeq`; `count=3`; D4 controls show `null` vs `AGENT_CAP` / timeout. |

## How this demo proves each line

- **Harness**: `demos/day5/AGENTS.md` plus the repository root `AGENTS.md` are
  both injected; the nested marker `D5-NESTED-AGENTS-V1` is searchable in the
  session log.
- **State**: turns 1–4 share one session id; the demo resumes with
  `--session-id` and never creates a second root session.
- **Context**: `spawn_teammate(context="fork")` sees the token from a completed
  Lead turn; `context="fresh"` answers `UNKNOWN`.
- **Verification**: the verification task is completed by Carol only after she
  runs `verify/static.sh`; the final `verify/verify_d5.py` is independent.
- **Loop**: the stop-condition overlay is applied to every turn, and the goal
  subsystem is checked from the effective config.
- **Graph**: the fan-out script is `flow/workflow.js`; the workflow result and
  routing events are extracted into `routing.md`.
