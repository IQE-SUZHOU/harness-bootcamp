# Session files on disk

Reference for the files that `dsh` persists, the naming rules, and the crash
repair contract observed in the Day 2 demo. Paths are generic; the demo
resolves the real store from `$DSH_HOME` (default `~/.dsh`).

## Layout

```
$DSH_HOME/
└── sessions/
    └── <projectKey>/
        └── session-<uuid>/
            ├── session.lock              # zero-byte write lease
            └── session.v4.jsonl.zstd     # zstd-compressed, append-only JSONL
```

A session id is `session-<uuid>`. It is stable across resume: `--session-id`
adopts the same directory instead of creating a new one.

## Project key

`projectKey(cwd)` turns the working directory into one directory name:

1. A run of `/`, `\`, or `:` becomes a single `-`.
2. Bytes in `[A-Za-z0-9._-]` stay literal; every other code unit (including
   `~`) becomes `~` plus four uppercase hex digits (for example `~0020`).
3. Leading `-` characters are removed; an empty slug becomes `root`.
4. The slug is truncated to 251 characters and wrapped in `--`.

Example: `/srv/work/harness-bootcamp` → `--srv-work-harness-bootcamp--`.

`demos/day2/projectkey.py` implements the same rule, so the demo can locate
the session directory without hard-coding a machine path.

## Log format

The first line is a header with no `seq`:

```json
{"type":"session","version":4,"id":"session-…","createdAt":1793932913405,
 "cwd":"…","isSeeded":false,"delegationDepth":0}
```

Every following line is one event with `seq` (0-based, monotonic), `time`
(epoch milliseconds), `type`, and `data`. The log is the source of truth for
the model-visible context; a resume replays it rather than re-injecting the
project instructions.

| Event | `data` (abridged) | Role |
| --- | --- | --- |
| `turn/start` | `turn` | Opens a user turn |
| `step/start` | `turn`, `step` | Opens one model/tool step |
| `assistant/message` | `message`, `usage` | Model output; usage carries `cacheReadTokens` / `cacheWriteTokens` |
| `tool/call` | `turn`, `step`, `callId`, `name`, `arguments` | Durable record of an intended tool call |
| `tool/result` | `message` (`toolCallId`, `isError`, `content`, `id`), `error` | Tool outcome |
| `step/end` | `turn`, `step` | Closes a step |
| `turn/end` | `turn`, `reason.kind` (`completed` or `interrupted`) | Closes a turn |
| `user/message` | `source.kind` (`user`, `agent-instructions`, `runtime-context`, `skill-catalog`) | Model-visible input |
| `request/header`, `request/context` | — | Model-visible request metadata |
| `session/end-seed` | — | Written on resume before the next turn |
| `agent/inbox/spliced` | `target`, `inserted` | Queues the next user message |

## Lifecycle

Normal turn:

```
turn/start → step/start → assistant/message → tool/call → tool/result
           → step/end → … → turn/end(completed)
```

Hard kill during a tool call:

```
turn/start → step/start → assistant/message → tool/call   [SIGKILL]
                                             │
                       no tool/result, no step/end, no turn/end
```

Resume after the crash:

```
synthetic tool/result (TOOL_OUTCOME_UNKNOWN)
→ step/end
→ turn/end(interrupted)
→ session/end-seed
→ agent/inbox/spliced
→ turn/start (new turn)
```

The repair closers reference the original call and event sequence. They state
that the outcome is unknown instead of inventing a result, so the model can
decide whether a retry is safe:

```json
{"type":"tool/result","seq":27,
 "data":{"turn":1,"step":2,"message":{
   "id":"interrupted-tool-result-call_…-27",
   "toolCallId":"call_…",
   "isError":true,
   "content":[{"type":"text","text":"The tool call was interrupted … Its outcome is unknown. … Do not retry blindly."}]},
   "error":{"name":"ToolOutcomeUnknownError","code":"TOOL_OUTCOME_UNKNOWN"}},
 "surfaceOp":"append","sourceEventSeqs":[26]}
```

## Observed run (2026-11-06, dsh 0.2.0-rc.2)

Normal session:

- events before resume: 23 (last `seq` 21)
- events after resume: 34
- resume `cacheReadTokens`: 6528
- resumed answer: still knows the earlier `1+1` question

Interrupted session:

| `seq` | Event | Note |
| --- | --- | --- |
| 20 | `tool/call` `bash` | starts `sleep 300` as background job `bash-1` |
| 21 | `tool/result` | job started |
| 25 | `assistant/message` | `cacheRead=6784` |
| 26 | `tool/call` `job_output` | waits for the job; **last durable event before SIGKILL** |
| 27 | `tool/result` | synthetic closer, `interrupted-tool-result-…-27` |
| 28 | `step/end` | closes turn 1 step 2 |
| 29 | `turn/end` | reason `interrupted` |
| 30 | `session/end-seed` | resume boundary |
| 31 | `agent/inbox/spliced` | queues `继续` |
| 32 | `turn/start` | turn 2 |
| 39 | `tool/call` `job_output` | first attempt after resume; returns `isError` because the old job record is gone |
| 45 | `tool/call` `job_list` | no background jobs |
| 51 | `tool/call` `bash` | the model re-runs the command |
| 57 | `tool/call` `job_output` | waits for the new job |
| 64 | `turn/end` | reason `completed` |

The model's post-resume answer explicitly said the first wait was interrupted
and the job record was lost, so it re-ran the command. That is the
context-lossless behavior required by D2.

## Inspecting a session

```bash
key="$(python3 demos/day2/projectkey.py "$PWD")"
session="$HOME/.dsh/sessions/$key/session-<uuid>"

zstd -dc "$session/session.v4.jsonl.zstd" > /tmp/events.jsonl
python3 demos/day2/analyze_session.py /tmp/events.jsonl --timeline
python3 demos/day2/analyze_session.py /tmp/events.jsonl --json
```
