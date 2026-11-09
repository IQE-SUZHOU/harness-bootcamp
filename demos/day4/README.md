# Day 4 · Loop / Graph / Automation Demo

Reproducible evidence for **D4 · fan-out/fan-in, stop conditions, and failure
propagation**.

The demo runs five real headless `dsh` sessions against the `workflow` tool:

1. a three-way fan-out (`ci`/`cd`/`iac`) followed by one fan-in summary;
2. an ordinary branch failure inside `parallel()`;
3. an illegal `agent()` option (fatal);
4. a three-agent fan-out under a two-agent total cap;
5. a six-second synchronous busy loop under a three-second script timeout.

Every run is checked twice: `render_evidence.py` derives the acceptance flags
from the raw output, and `verify_d4.py` re-derives them independently without
an LLM. The demo exits non-zero if either layer fails.

## What each run proves

| Run | Prompt | Expected observation |
| --- | --- | --- |
| `fanout` | [`prompts/fanout.txt`](prompts/fanout.txt) | `completed (4 agents)`, `count: 3`, three non-empty parts plus a summary |
| `partial` | [`prompts/partial.txt`](prompts/partial.txt) | `completed`, results `["OK1", null, "OK2"]` |
| `fatal` | [`prompts/fatal.txt`](prompts/fatal.txt) | whole run fails: `option "bogusOption" is not recognized` |
| `cap` | [`prompts/cap.txt`](prompts/cap.txt) | whole run fails: `total agent cap (2)` |
| `timeout` | [`prompts/timeout.txt`](prompts/timeout.txt) | whole run fails: `Script execution timed out after 3000ms` |

The prompts instruct the model to execute the script verbatim and to stop
after the tool result. The `singleWorkflowCallPerRun` check proves the negative
controls did not retry and dilute the evidence.

## Stop conditions

[`stop-condition.yml`](stop-condition.yml) is applied as a `--patch` overlay:

```yaml
- id: workflow-ptc
  config:
    provider: spawn
    maxConcurrentAgents: 2        # explicit; 0 means "auto", not "disabled"
    maxTotalAgents: 10            # per-run runaway backstop
    maxItemsPerCall: 8            # parallel()/pipeline() item ceiling
    syncTimeoutMs: 3000           # initial synchronous VM slice
- id: goal
  config:
    defaultMaxGoalRounds: 20      # auto-continuation exit condition
```

| Control | Engine default | Demo value | Effect when exceeded |
| --- | --- | --- | --- |
| `maxTotalAgents` | `1000` | `10` (`2` in the cap run) | `AGENT_CAP`, whole run fails |
| `maxConcurrentAgents` | `0` (auto) | `2` | FIFO queueing, observed as `maxActive = 2` |
| `maxItemsPerCall` | `4096` | `8` | item cap error |
| `syncTimeoutMs` | `5000` | `3000` | script timeout error |
| `defaultMaxGoalRounds` | `256` | `20` | goal stops auto-continuing |

`0` for `maxConcurrentAgents` is **not** "no concurrency": the engine computes
`min(16, max(1, availableParallelism() - 2))`. The demo uses an explicit
positive value so the limit is observable.

`maxTotalAgents` is the deployment ceiling. A single run may request a lower
value, but not a higher one; the cap overlay lowers it to `2` for one run.

## Fan-out / fan-in

The fan-out script uses `parallel()` for three labelled branches, filters out
failed items, and passes the survivors to a fourth `agent()`:

```js
phase("fan-out");
const parts = await parallel([
  () => agent("用一句话说明什么是 CI。只输出一句话。", { label: "ci", phase: "fan-out" }),
  () => agent("用一句话说明什么是 CD。只输出一句话。", { label: "cd", phase: "fan-out" }),
  () => agent("用一句话说明什么是 IaC。只输出一句话。", { label: "iac", phase: "fan-out" }),
]);
phase("fan-in");
const good = parts.filter(Boolean);
const summary = await agent("把下面三句话合并成一段不超过 80 字的总述...", {
  label: "summary",
  phase: "fan-in",
});
return { count: good.length, parts, summary };
```

Two properties matter:

- `parallel()` has **no cross-item barrier**; all thunks start concurrently,
  subject only to `maxConcurrentAgents`.
- results are returned in **input order**, not completion order. The fan-in
  branch starts only after every fan-out branch has ended; `routing.md` proves
  this by comparing `summary.startSeq` with the maximum branch `endSeq`.

Failed items are `null`. The correct fan-in therefore uses
`parts.filter(Boolean)`; `parts.length` would count failures as successes, and a
bare `join()` would turn `null` into the literal string `"null"`.

## Routing is observable

Every branch is a real child session. The parent session records:

| Event | Payload used here |
| --- | --- |
| `tool-workflow/run-start` | `runId`, workflow `name` |
| `subagent/catalog` | `childId`, `mode` |
| `tool-workflow/agent-start` | `runId`, agent `seq`, `label`, `childId` |
| `tool-workflow/agent-end` | `runId`, agent `seq`, `outcome` |
| `tool-workflow/run-end` | `runId`, `stopReason` |

`workflow_tools.py workflow-events` pairs start/end by `(runId, agent.seq)` and
computes `maxActive` from the event timestamps. The resulting
[`evidence/routing.md`](evidence/routing.md) is the routing explanation: script
`label` → agent `seq` → `childId` → start/end sequence and duration.

`phase()` and `log()` are display hooks, not routing keys. Phases are inferred
from the script's labels in the trace; the authoritative correlation is the
agent `seq`.

## Failure propagation

| Failure class | Example | `parallel()`/`pipeline()` behavior |
| --- | --- | --- |
| Ordinary branch error | `throw new Error(...)` | that item becomes `null`; other items complete |
| Illegal argument / schema | unknown `agent()` option, bad schema | fatal `WorkflowError`; whole run fails |
| Engine cap | `maxTotalAgents` reached | `AGENT_CAP`; whole run fails |
| Script timeout | synchronous slice exceeds `syncTimeoutMs` | timeout error; whole run fails |

The distinction is explicit: option/schema mistakes are fatal before an agent
starts, while a child-agent failure only nulls its slot. No negative control
returns a partial success envelope.

The script return value must be plain JSON. Sparse arrays, array properties,
cycles, class instances, functions, `undefined`, non-finite numbers, and symbol
keys are rejected as `RESULT_UNSERIALIZABLE`. The demo's `resultIsPureJson`
check confirms the fan-out returned an object that survived serialization.

## Auto loop · Goal

The goal subsystem separates four layers:

| Layer | Package | Role |
| --- | --- | --- |
| Service | `@deepseek-ai/dsh-goal` | Stores durable goal state; **does not schedule work** |
| Driver | `@deepseek-ai/dsh-goal-round-driver` | Advances rounds while the goal is active and continuation is armed |
| Tool | `@deepseek-ai/dsh-tool-goal` | Model-facing get/create/update |
| Command | `@deepseek-ai/dsh-command-goal` | `/goal` user interface |

`defaultMaxGoalRounds` is the auto-loop exit condition. Mounting only
`dsh-goal` stores and serves goals but never starts a round. Goal state is
durable across turns, resume, and process restart; the **continuation permit
(armed) is process-local**, so a restarted process must re-arm it.

This demo verifies the cap and the four mounted layers from the effective
config (`auto-loop.json`). It does not drive a goal to completion, because that
would require an open-ended model loop; the workflow stop conditions above are
the bounded, reproducible part of D4.

## Acceptance checks

`demos/day4/evidence/summary.json` records each flag:

| Flag | Meaning |
| --- | --- |
| `fanoutRan` | Four agents started; `count=3`; parts and summary are non-empty |
| `fanInRan` | `summary.startSeq` is after every fan-out branch `endSeq` |
| `routingExplained` | Four labelled branches with child IDs and paired start/end |
| `partialFailureIsNull` | Ordinary branch failure yields `[str, null, str]` |
| `fatalStopsWholeRun` | Illegal option fails the whole workflow, no return value |
| `agentCapEnforced` | `maxTotalAgents: 2` produces `total agent cap (2)` |
| `syncTimeoutEnforced` | Six-second busy loop is stopped at `3000ms` |
| `goalRoundCapConfigured` | Explicit `defaultMaxGoalRounds: 20`; four goal layers mounted |
| `concurrencyCapped` | Observed `maxActive = 2` matches the configured cap |
| `stopConditionConfigured` | Effective `workflow-ptc` config equals the committed overlay |
| `singleWorkflowCallPerRun` | Each run used exactly one workflow call |
| `resultIsPureJson` | Fan-out return value is a JSON object |

`verify_d4.py` re-checks all of the above as V1–V13, plus a leakage scan
(absolute home paths and `sk-` tokens), and writes `verifier-result.json`.

## Requirements

- `dsh` on `PATH` (tested with 0.2.0-rc.2), with a working headless profile
- `zstd`
- `python3`
- A provider account with available quota

`DSH_PATCH` may point at a dsh patch overlay to select another provider route.
The demo applies it before the stop-condition overlay.

## Run

```bash
./demos/day4/loop-graph-demo.sh
```

Overrides:

```bash
DSH=/path/to/dsh DSH_TIMEOUT=900 DSH_PATCH=/path/to/model.yml \
  ./demos/day4/loop-graph-demo.sh
```

Each run gets its own `timeout` wrapper (`DSH_TIMEOUT`, default 600 seconds).
The five sessions share no state; `dsh` persists them under
`$DSH_HOME/sessions/`.

## Output

Raw output goes to `d4-artifacts/` (git-ignored):

| Path | Content |
| --- | --- |
| `workspace/` | Working directory for all runs |
| `runs/*.ndjson` | Headless NDJSON events for each run |
| `runs/*.err` | stderr for each run |
| `runs/*.events.jsonl` | Decompressed persisted sessions |
| `runs/*.sid` | Session IDs |
| `effective-config.yml` | Full composed profile after the overlay |

The sanitized snapshot in [`evidence/`](evidence/) contains:

| File | Content |
| --- | --- |
| `summary.json` | Acceptance flags, run results, routing, runtime, stop conditions |
| `evidence.md` | Human-readable acceptance, config, fan-out/fan-in, failure table |
| `routing.md` | Per-branch `seq`, label, child ID, duration, outcome |
| `graph.mmd` | Mermaid fan-out/fan-in graph |
| `stop-condition.json` | Effective `workflow-ptc` config |
| `auto-loop.json` | Goal round cap and mounted layers |
| `<run>.json` | Extracted workflow call, script, meta, result/error |
| `<run>.events.json` | Paired workflow routing events |
| `<run>.runtime.json` | Permission/sandbox/model facts for that session |
| `runtime.json` | Environment summary across all five sessions |
| `verifier-result.json` | Independent V1–V13 verifier output |

## Boundaries

- The demo writes `d4-artifacts/` inside this repository and `dsh` session
  state under `$DSH_HOME/sessions/`; nothing else.
- Committed evidence replaces the repository root, home directory, and
  `DSH_HOME` with `<repo-root>`, `<home>`, and `<dsh-home>`, and filters
  `sk-`-style tokens.
- The negative-control prompts intentionally contain a branch failure, an
  unknown option, and a busy loop. Do not "fix" them.

## Tools

- `workflow_tools.py` — session IDs, workflow result extraction, routing
  events, runtime facts, effective config, goal config, environment summary.
- `render_evidence.py` — renders `summary.json`, `evidence.md`, `routing.md`,
  `graph.mmd`.
- `verify_d4.py` — independent non-LLM verifier (V1–V13).
