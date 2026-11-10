# mini-agent

A minimal, dependency-free coding agent modeled on the DeepSeek Harness
architecture.

It keeps the harness's essential design — a **turn/step agent loop**, a **durable session log** that every request is derived from, a **tool registry** with JSON-Schema validation, and a **provider adapter** abstraction — but drops the Cordis plugin runtime, the session persistence backends, the GUI, and the type-graph machinery. The result is a few hundred lines that run anywhere Node 22+ is installed, with **zero npm dependencies**.

## Quick start

```sh
cd demos/day5/mini-agent

export DEEPSEEK_API_KEY=sk-...

# One-shot task
node --experimental-strip-types src/cli/main.ts "list the files in this directory"

# Interactive session
node --experimental-strip-types src/cli/main.ts -i

# Unit and wire-protocol tests; no network, no API key
./tests/run-tests.sh
```

`node --experimental-strip-types` runs the TypeScript sources directly — no build step. On Node 23.6+ the flag is unnecessary.

## Using a different model API

The agent talks to any endpoint that speaks the **OpenAI Chat Completions** protocol (OpenAI, MiniMax, Moonshot, Qwen, Together, Groq, vLLM, Ollama, LM Studio, …) or the **DeepSeek Messages** protocol.

Four routes are pre-registered:

| Route | Endpoint | Key |
| --- | --- | --- |
| `deepseek` | `https://api.deepseek.com` | `$DEEPSEEK_API_KEY` |
| `openai` | `https://api.openai.com/v1` | `$OPENAI_API_KEY` |
| `minimax` | `https://api.minimaxi.com/v1` | `$MINIMAX_API_KEY` |
| `minimax-intl` | `https://api.minimax.io/v1` | `$MINIMAX_API_KEY` |

```sh
node --experimental-strip-types src/cli/main.ts --provider minimax --model MiniMax-M3.1-Flash "task"
```

> MiniMax issues separate keys for its China and international platforms, and
> each platform rejects the other's key. Use `minimax` for a China key and
> `minimax-intl` for an international one.

Declare other endpoints in a `providers.json` file, then select one by name:

```json
{
  "providers": {
    "my-llm": {
      "kind": "openai",
      "baseURL": "https://my-llm.example.com/v1",
      "apiKey": "${MY_LLM_API_KEY}"
    }
  }
}
```

```sh
node --experimental-strip-types src/cli/main.ts --provider my-llm --model my-model "task"
node --experimental-strip-types src/cli/main.ts --list-providers
```

For a protocol of your own, write one adapter class. See **[docs/custom-model-api.md](docs/custom-model-api.md)** for the full guide: config file format, the chunk protocol, adapter authoring, MiniMax-specific settings, and troubleshooting.

## Options

| Option | Meaning |
| --- | --- |
| `-i`, `--interactive` | Read tasks from stdin, one per line (`exit` quits) |
| `--provider <name>` | Provider route to use (default `deepseek`, or `$MINI_AGENT_PROVIDER`) |
| `--model <id>` | Model id (default `deepseek-chat`, or `$MINI_AGENT_MODEL`) |
| `--cwd <path>` | Workspace root for tools (default: current directory) |
| `--base-url <url>` | API endpoint override |
| `--api-key <key>` | API key override |
| `--temperature <n>` | Sampling temperature |
| `--max-steps <n>` | Stop the turn after this many model requests |
| `--timeout-ms <n>` | Stop the turn after this many milliseconds |
| `--max-total-tokens <n>` | Stop the turn after this many tokens |
| `--prune-threshold <n>` | Prune a tool result above this many characters |
| `--prune-head <n>` | Keep this many leading characters when pruning |
| `--prune-tail <n>` | Keep this many trailing characters when pruning |
| `--session-id <id>` | Persist under this id and resume it when it exists |
| `--store <path>` | Directory holding the persisted sessions |
| `--list-sessions` | List the persisted sessions and exit |
| `--verify <file>` | Verify the workspace against a DoD spec, then exit |
| `--workflow <file>` | Run a fan-out / fan-in workflow, then exit |
| `--log` | Print the session event log when finished |
| `--list-providers` | List the registered provider routes and exit |

### Environment

| Variable | Meaning |
| --- | --- |
| `DEEPSEEK_API_KEY` | Key for the `deepseek` route |
| `DEEPSEEK_BASE_URL` | Endpoint override for the `deepseek` route |
| `OPENAI_API_KEY` | Key for the `openai` route |
| `OPENAI_BASE_URL` | Endpoint override for the `openai` route |
| `MINIMAX_API_KEY` | Key for the `minimax` route |
| `MINIMAX_BASE_URL` | Endpoint override for the `minimax` route |
| `MINIMAX_REASONING_EFFORT` | MiniMax thinking depth (`low`…`max`) |
| `MINI_AGENT_PROVIDER` | Default provider route |
| `MINI_AGENT_MODEL` | Default model id |
| `MINI_AGENT_CONFIG` | Path to a `providers.json` file |
| `MINI_AGENT_MAX_STEPS` | Step cap for one turn |
| `MINI_AGENT_TIMEOUT_MS` | Turn deadline in milliseconds |
| `MINI_AGENT_MAX_TOTAL_TOKENS` | Token budget for one turn |
| `MINI_AGENT_PRUNE_THRESHOLD` | Tool-result pruning threshold |
| `MINI_AGENT_PRUNE_HEAD` | Leading characters kept when pruning |
| `MINI_AGENT_PRUNE_TAIL` | Trailing characters kept when pruning |
| `MINI_AGENT_SESSION_ID` | Default session id |
| `MINI_AGENT_STORE` | Directory holding the persisted sessions |

## Built-in tools

| Tool | Purpose |
| --- | --- |
| `bash` | Run a shell command in the workspace; returns combined stdout/stderr |
| `read_file` | Read a UTF-8 text file, with optional `offset` and `limit` |
| `write_file` | Write UTF-8 text, creating parent directories |
| `edit_file` | Replace an exact string; the match must be unique |

Every file tool resolves paths against the workspace root and **refuses** a path that escapes it.

## Architecture

```
src/
├── core/
│   ├── types.ts     Content blocks, tool schemas, request/response types
│   ├── session.ts   Append-only event log; deriveMessages() projects the request
│   ├── tools.ts     Tool registry and JSON-Schema validation
│   ├── llm.ts       LlmAdapter interface and the streaming BlockAssembler
│   ├── providers.ts Provider registry: name → adapter factory
│   ├── config.ts    providers.json loading and adapter construction
│   ├── stop-conditions.ts  Step, time, and token limits for one turn
│   ├── prune.ts     Model-free tool-result pruning
│   ├── persistence.ts  Durable session store and crash repair
│   ├── repository.ts   Session lifecycle: create, save, resume
│   ├── verify.ts    Definition-of-Done verification (independent, non-LLM)
│   ├── approval.ts  Fail-closed human approval gate
│   ├── workflow.ts  Fan-out / fan-in and failure propagation
│   └── agent.ts     The turn/step loop
├── llm/
│   ├── deepseek.ts  DeepSeek Messages API adapter (SSE streaming)
│   └── openai.ts    OpenAI-compatible Chat Completions adapter (SSE streaming)
├── tools/
│   └── builtin.ts   bash, read_file, write_file, edit_file
├── cli/
│   └── main.ts      Command-line entry point
└── index.ts         Public library entry point
```

### The turn/step loop

A **turn** is one user input. A **step** is one model request plus the tool calls it produced.

```
user input
   │
   ├─ step 1: model request → tool call → execute tool → log result
   ├─ step 2: model request → tool call → execute tool → log result
   └─ step N: model request → text only → turn ends
```

The loop keeps stepping while the model asks for tools, and ends the turn when the model answers with text alone. A tool failure is reported *to the model* as a failed result, so the model can recover, rather than aborting the turn.

### Stop conditions

Without a limit, a task that sends the model in circles never ends: the loop
keeps stepping for as long as the model asks for tools. A **stop condition**
caps that, and each cap reports *why* it tripped instead of ending silently.

| Limit | Flag | Environment | Ends the turn when |
| --- | --- | --- | --- |
| Step cap | `--max-steps <n>` | `MINI_AGENT_MAX_STEPS` | the turn made `n` model requests |
| Deadline | `--timeout-ms <n>` | `MINI_AGENT_TIMEOUT_MS` | the turn ran for `n` milliseconds |
| Token budget | `--max-total-tokens <n>` | `MINI_AGENT_MAX_TOTAL_TOKENS` | the turn consumed `n` tokens |

```sh
node --experimental-strip-types src/cli/main.ts --max-steps 5 --timeout-ms 60000 "task"
```

The limits are checked **before** each model request, so a tripped limit ends
the turn without spending another call. The step cap is checked first: it is
the cheapest and the most predictable brake on a runaway loop.

A tripped limit ends the turn with the reason `stopped`, recorded in the
session log's `turn/end` event:

```json
{"kind": "turn/end", "turn": 1,
 "reason": {"kind": "stopped", "stopKind": "max-steps",
            "message": "the turn reached its limit of 5 steps"}}
```

The CLI prints the same reason on stderr:

```
[stopped] max-steps: the turn reached its limit of 5 steps
```

An unset limit never trips, so a run without stop conditions behaves exactly as before. A non-positive limit is rejected when the agent is constructed, not silently ignored.

### Tool-result pruning

Tool output is the fastest-growing part of a context: one `read_file` on a big
file can add tens of thousands of characters, and the agent re-sends the whole
history on every request. **Pruning** keeps each tool result within a
character budget by dropping its **middle** and keeping its head and tail, so
the model still sees how the output began and ended.

| Budget | Flag | Environment | Default | Meaning |
| --- | --- | --- | --- | --- |
| Threshold | `--prune-threshold <n>` | `MINI_AGENT_PRUNE_THRESHOLD` | 8192 | prune a result above this many characters |
| Head | `--prune-head <n>` | `MINI_AGENT_PRUNE_HEAD` | 4096 | leading characters kept |
| Tail | `--prune-tail <n>` | `MINI_AGENT_PRUNE_TAIL` | 1024 | trailing characters kept |

```sh
node --experimental-strip-types src/cli/main.ts \
  --prune-threshold 2000 --prune-head 800 --prune-tail 200 "task"
```

Three properties make this safe:

- **Model-free.** Pruning costs no tokens and no extra request. It is
  deterministic, so the same log always prunes to the same request.
- **The durable log is never rewritten.** Pruning happens in the projection
  from the log into the request, so the full-fidelity result stays in the log
  and the session remains replayable.
- **Slicing is by Unicode code point**, so a retained boundary never splits a
  surrogate pair. The removed middle is replaced by one marker.

A pruned result looks like this:

```
<the first 800 characters>

[... tool result middle pruned ...]

<the last 200 characters>
```

The emitted size is `head + marker + tail`, so that sum must fit inside the
threshold; a configuration that cannot satisfy this is rejected at startup
rather than silently mis-pruning.

### The session log is the source of truth

Every event is appended to `Session` with a monotonic sequence number. The model request is derived from that log by `deriveMessages()`, never assembled ad hoc. Two consequences fall out of this:

- **A session is replayable.** The same log always produces the same request.
- **Tool calls and results stay adjacent.** The provider requires each `tool_result` to directly follow the assistant message that requested it; the projection enforces that ordering.

### Persistence and crash repair

A session that lives only in memory cannot survive the process. With a
`--session-id`, the log is written to disk as append-only JSONL after every
turn, and the same id resumes the stored log on the next run.

```sh
# first run: the log is persisted
mini-agent --session-id demo-1 "记住：我的幸运数字是 42"

# second run: the stored history is replayed, so the model still knows
mini-agent --session-id demo-1 "我的幸运数字是多少？"
```

The store also **repairs** a log that a crash cut short. An open tool call, a
step, and a turn are closed with explicit records, in that order:

```
synthetic tool/result (the outcome is unknown)
→ step/end
→ turn/end(reason: interrupted)
```

The repair **never invents a tool result**. A call whose outcome is unknown is
recorded as an error that says so, so the model can decide whether a retry is
safe:

> The tool call was interrupted before its result was recorded. Its outcome is
> unknown. Do not retry blindly: check the workspace state first.

A torn last line — the partial write a crash leaves behind — is dropped, and
the rest of the log survives.

```sh
mini-agent --list-sessions   # show the stored sessions and what is open
```

### Definition-of-Done verification

An agent's claim that a task is done is not evidence. A **verifier** is: it
re-reads the workspace and re-runs the acceptance commands, so a claim that
skips the work fails.

The verifier is **independent and non-LLM**: every item is decided from the
workspace, never from a model report. That makes it cheap, reproducible, and
impossible to persuade.

```sh
mini-agent --verify dod.json
```

```json
{
  "workspace": "/path/to/workspace",
  "files": [
    { "id": "D1", "item": "answer.txt holds 42", "path": "answer.txt", "contains": ["42"] },
    { "id": "D2", "item": "notes.md is absent", "path": "notes.md", "mustExist": false }
  ],
  "commands": [
    { "id": "C1", "item": "the check script passes", "command": "./scripts/check.sh", "args": [], "expectExit": 0 }
  ],
  "protectedFiles": [{ "path": "dod.md", "sha256": "…" }],
  "forbiddenPaths": ["CANARY_DO_NOT_CREATE"]
}
```

The command exits `0` when every item passes and `1` otherwise, and prints the
evidence for each decision:

```
| ID | Item | Result | Evidence |
| --- | --- | --- | --- |
| D1 | answer.txt holds 42 | PASS | answer.txt satisfies the rule |
| C1 | the check script passes | FAIL | `./scripts/check.sh` exited 1, expected 0 |
```

A `protectedFiles` entry pins a file's digest, so the verifier also proves the
agent did not edit the acceptance criteria to make them pass.

### Human approval gate

Some work may only proceed after a human says so. The gate is **fail-closed**:
with no approver configured, or with an approver that throws, the request is
refused. The agent cannot approve its own work — the approval comes from
outside the model.

```ts
const gate = new ApprovalGate(async request => {
  const answer = await askHuman(request)
  return answer ? { kind: 'approved', token: generateApprovalToken() } : { kind: 'rejected', reason: 'no' }
})
const decision = await gate.request({ action: 'write the release tag', reason: 'the task is done' })
```

A granted approval always carries a token, so a later verifier can check that
the work really was approved rather than merely claiming it was. The token
prefix is `APPROVED-BY-HUMAN-`.

### Fan-out / fan-in

A workflow runs several branches concurrently and then summarizes the
survivors. The failure semantics are the point:

| Failure class | Effect |
| --- | --- |
| An ordinary branch error | that branch becomes `null`; the others complete |
| A fatal error (cap reached, timeout) | the whole run fails |

A fan-in therefore filters out the `null`s. Counting `parts.length` would
count failures as successes.

```sh
mini-agent --workflow workflow.json
```

```json
{
  "branches": [
    { "label": "ci", "task": "用一句话说明什么是 CI。" },
    { "label": "cd", "task": "用一句话说明什么是 CD。" }
  ],
  "fanIn": "把下面三句话合并成一段不超过 80 字的总述。",
  "limits": { "maxConcurrent": 2, "maxTotal": 10 }
}
```

The limits mirror the harness's own: `maxConcurrent` bounds the branches
running at once, `maxTotal` is the deployment ceiling, and a branch or run
timeout is fatal. An omitted or zero `maxConcurrent` means *auto*
(`min(16, max(1, parallelism - 2))`), never "no concurrency".

The run reports the parts, the summary, and the routing record that pairs each
branch with its outcome.

### Provider adapters

The agent loop never talks to a provider directly. It sees only `StreamChunk`s:

```
block-start → text-delta → text-delta → block-end → usage → finish
```

`BlockAssembler` turns that back into complete content blocks. Adding a provider means implementing one `LlmAdapter` — nothing else in the core changes.

The `ProviderRegistry` maps a provider *name* to an adapter factory, so the CLI can select `--provider my-llm` without the core importing every adapter. `providers.json` fills that registry at startup.

## Tests

```sh
./tests/run-tests.sh
# or, equivalently
node --experimental-strip-types --test tests/*.test.ts
```

113 tests cover the session projection, schema validation, block assembly, the turn/step loop (including tool failures and argument rejection), the stop conditions (step cap, deadline, and token budget, plus their boundaries), tool-result pruning (budgets, boundaries, surrogate pairs, idempotence, and log fidelity), session persistence and crash repair (including a torn last line and an unknown-outcome closer), Definition-of-Done verification, the fail-closed approval gate, fan-out / fan-in and the failure-propagation semantics, the built-in tools, the provider registry and config loading, the MiniMax request shape, `reasoning_content` handling, and tool calls split across chunks, and the full HTTP + SSE wire round trip against local mock servers for both the DeepSeek and OpenAI wire formats.

## Using it as a library

```ts
import { Agent, ToolRegistry, DeepSeekAdapter, createBuiltinTools } from './src/index.ts'

const registry = new ToolRegistry()
for (const tool of createBuiltinTools(process.cwd())) registry.register(tool)

const adapter = new DeepSeekAdapter({ apiKey: process.env.DEEPSEEK_API_KEY! })
const agent = new Agent(adapter, registry, {
  provider: adapter.provider,
  model: 'deepseek-chat',
  systemPrompt: 'You are a helpful assistant.',
  onText: (text) => process.stdout.write(text),
})

const result = await agent.run('What is 2 + 2?')
console.log(result.reason, result.text)
```

## Relation to the full harness

| Harness | mini-agent |
| --- | --- |
| `dsh-agent-loop` (`ReactLoopAgent`) | `core/agent.ts` |
| `dsh-session` (event log + projections) | `core/session.ts` |
| `dsh-tools` (registry + `defineTool`) | `core/tools.ts` |
| `dsh-llm` (`LlmAdapter`, `BlockAssembler`) | `core/llm.ts` |
| `dsh-llm-deepseek` | `llm/deepseek.ts` |
| `dsh-llm-deepseek` credential + config | `core/config.ts`, `core/providers.ts` |
| `dsh-tool-bash` and friends | `tools/builtin.ts` |
| `workflow-ptc` / `goal` stop conditions | `core/stop-conditions.ts` |
| `dsh-compaction-tool-result-pruner` | `core/prune.ts` |
| `dsh-session` persistence + crash repair | `core/persistence.ts`, `core/repository.ts` |
| D3 `verify_dod.py` (independent DoD verifier) | `core/verify.ts` |
| D3 human gate (approval token) | `core/approval.ts` |
| D4 `workflow` tool (fan-out / fan-in) | `core/workflow.ts` |
| Cordis plugin runtime, GUI, SDK | *not included* |

The wire protocol matches the harness's DeepSeek adapter: `POST {baseURL}/v1/messages` with an Anthropic-style Messages body, `x-api-key` authentication, and SSE streaming. The OpenAI adapter additionally covers the Chat Completions protocol the harness does not implement.

The stop conditions cover the harness's per-turn caps in a simpler form: a step count, a deadline, and a token budget. The workflow adds the harness's `maxConcurrentAgents` and `maxTotalAgents` caps. The harness's goal round cap is not included, because the mini-agent has no goal layer.

Pruning follows the harness's `dsh-compaction-tool-result-pruner`: it keeps a tool result's head and tail, replaces the middle with a marker, slices by Unicode code point, and never rewrites the durable log. The harness's summarizer-based compaction is not included.

Persistence follows the harness's D2 contract: an append-only JSONL log, one directory per session, and a repair that closes an interrupted tool call, step, and turn with an *unknown outcome* rather than an invented result.

The workflow follows the harness's D4 failure semantics: an ordinary branch error nulls its slot and the run continues, while a cap or a timeout fails the whole run. Nothing returns a partial success envelope.

## Limitations

- **Two protocols.** The DeepSeek Messages API and the OpenAI Chat Completions API. Other protocols need a new adapter.
- **Persistence is one file per session.** The harness stores zstd-compressed logs under a project key; the mini-agent stores plain JSONL under a session id, with no project-key derivation.
- **No sandbox.** The `bash` tool runs commands directly; the file tools are confined to the workspace root, but the shell is not.
- **No context compaction.** Tool results are pruned, but the conversation itself is not summarized: a long exchange of short messages still grows without bound. The harness compacts with a summarizer model; the mini-agent does not.
- **No context-window awareness.** The agent does not know how large the model's window is, so it cannot size its budgets automatically or pre-empt a `context_length_exceeded` error.
- **The approval gate is a library, not a CLI command.** The gate exists and is fail-closed, but the CLI has no interactive prompt wired to it.
- **The verifier is a library and a `--verify` command.** The D3 maker-checker *loop* — a checker rejecting a maker and the maker repairing in a bounded retry — is not driven automatically; the verifier and the gate are the pieces a caller composes into one.
- **Stop conditions are per turn.** A cap ends the current turn; it does not carry over to the next one, and the loop does not resume the unfinished task on its own.
