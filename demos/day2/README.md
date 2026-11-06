# Day 2 · Interrupt → Resume Demo

Reproducible evidence for **D2 · State / Context / Persistence**.

The demo drives a real `dsh` headless session through four states:

1. **Normal run** — ask a question, persist the session, record its id.
2. **Normal resume** — adopt the same session id and check that the earlier
   turn is still in context and the KV cache is reused.
3. **Hard kill** — start a long-running tool call, wait until the call is
   durably recorded, then `SIGKILL` the whole process group.
4. **Crash resume** — adopt the interrupted session id and verify that `dsh`
   repairs the log before running the next turn: a synthetic tool result, a
   `step/end`, and a `turn/end` with reason `interrupted`.

## Requirements

- `dsh` on `PATH` (tested with 0.2.0-rc.2), with a working headless profile
- `zstd`
- `python3`

## Run

```bash
./demos/day2/interrupt-resume-demo.sh
```

The script writes its output to `d2-artifacts/` by default. Override it with
`D2_OUT_DIR`:

```bash
D2_OUT_DIR=/tmp/d2 ./demos/day2/interrupt-resume-demo.sh
```

It writes only to the output directory and to the `dsh` session store
(`$DSH_HOME/sessions/`, default `~/.dsh/sessions/`). The script is
non-interactive and exits non-zero if any acceptance check fails.

## Acceptance checks

| Check | Meaning |
| --- | --- |
| `session_file_created` | The session directory contains `session.v4.jsonl.zstd` |
| `event_log_readable` | The compressed event log decompresses and has a monotonic `seq` |
| `normal_resume_lossless` | The resumed turn still knows the previous `1+1` question |
| `kv_cache_reused` | The normal resume reports `cacheReadTokens > 0` |
| `baseline_injected_once` | `AGENTS.md` is injected exactly once in the first turn |
| `interrupted_turn_visible` | The killed session has an open `turn/start` |
| `interrupted_step_visible` | The killed session has an open `step/start` |
| `interrupted_tool_call_visible` | The killed session has a `tool/call` with no result |
| `interrupted_tool_result_closer` | Resume appends a synthetic interrupted tool result |
| `interrupted_turn_end_closer` | Resume appends `turn/end` with reason `interrupted` |
| `open_turns_closed` | No turn remains open after resume |
| `open_steps_closed` | No step remains open after resume |
| `baseline_still_once` | Resume does not inject `AGENTS.md` a second time |

## Output

| Path | Content |
| --- | --- |
| `run1.ndjson` | Headless NDJSON events for the normal run |
| `resume1.ndjson` | Headless NDJSON events for the normal resume |
| `kill.ndjson` | Partial NDJSON from the process that was killed |
| `resume2.ndjson` | Headless NDJSON events for the crash resume |
| `events-*.jsonl` | Decompressed session logs at each stage |
| `timeline-*.txt` | One line per session event, with `seq` |
| `*-summary.json` | Open turns, open steps, open tool calls, cache usage |
| `summary.json` | Machine-readable evidence for all checks |
| `evidence.md` | Human-readable pass/fail table |

`d2-artifacts/` is git-ignored. A sanitized snapshot of one run is checked in
under [`evidence/`](evidence/) for reviewers; see
[`state/session-files.md`](state/session-files.md) for the on-disk layout,
the project-key algorithm, the event vocabulary, and the lifecycle diagram.

## Tools

- `projectkey.py <path>` — print the `dsh` project key for a working directory.
- `analyze_session.py <events.jsonl> [--timeline|--json]` — summarize a
  decompressed session log: open turns/steps/tool calls, interrupted closers,
  cache tokens, and baseline instruction injections.
