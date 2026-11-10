# D5 Definition of Done

Every item is decidable by `verify/static.sh` or by reading the named file. The
check ids match `verify/verify_d5.py` and `verifier-result.json`.

| ID | DoD item | Decidable evidence |
| --- | --- | --- |
| V1 | The `d5-super-agent` skill is discovered and loaded | `skill` tool call/result contains `D5-SUPER-AGENT-SKILL-V1` |
| V2 | The nested D5 instructions are injected | `user/message` with `source.kind=agent-instructions` contains `D5-NESTED-AGENTS-V1` |
| V3 | One durable session is resumed across four turns | one session id, at least four `turn/start` events, four turn logs |
| V4 | The Team board has the six expected tasks | latest `team/task` snapshots include all six subjects |
| V5 | `integration` is blocked by the four workstreams | its creation snapshot `blockedBy` contains the four ids |
| V6 | Every task is completed with a recorded owner | six `completed` snapshots; owners map to `lead`, `fork-auditor`, `carol` |
| V7 | A stale compare-and-set claim is rejected | Bob's child log has a `team_task_update` result with `stale` and revision 2 |
| V8 | Fork inherits the Lead's completed turns | fork child log contains `SA-WCF-D5-7F3A`; closing message has the token |
| V9 | Fresh spawn has an empty context | fresh child log does not contain the token; closing message is `UNKNOWN` |
| V10 | The three-way fan-out completes | workflow result `completed (4 agents)`, `count=3` |
| V11 | Fan-in starts after every branch | `summary.startSeq` is greater than all branch `endSeq` values |
| V12 | The workflow stop conditions are effective | effective `workflow-ptc` config equals `flow/limits.yml` |
| V13 | The goal auto-loop has a round cap | `defaultMaxGoalRounds=20`; four goal layers mounted |
| V14 | The D3 static DoD check passes inside the run | Carol's child log shows `d5 static checks passed` |
| V15 | The assessment log is derived from the session log and Team board | `evidence/assessment.md` has six tasks, owners, statuses, and evidence refs |
| V16 | The six-line teach-back covers every main line | final answer has Harness/State/Context/Verification/Loop/Graph with evidence refs |
| V17 | The committed evidence is sanitized | no absolute home paths, no `sk-` API tokens, no raw session log |

## Human checklist

- [ ] `./super-agent-demo.sh` exits 0.
- [ ] `evidence/assessment.md` lists six tasks, six teach-back lines, and the
      acceptance table.
- [ ] `evidence/verifier-result.json` has `allPassed: true` and `failed: []`.
- [ ] The Team board shows no task left `pending` or `in_progress`.
- [ ] The Lead's final answer names all six main lines with concrete evidence.
