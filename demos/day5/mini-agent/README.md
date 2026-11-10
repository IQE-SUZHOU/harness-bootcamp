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

### The session log is the source of truth

Every event is appended to `Session` with a monotonic sequence number. The model request is derived from that log by `deriveMessages()`, never assembled ad hoc. Two consequences fall out of this:

- **A session is replayable.** The same log always produces the same request.
- **Tool calls and results stay adjacent.** The provider requires each `tool_result` to directly follow the assistant message that requested it; the projection enforces that ordering.

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

33 tests cover the session projection, schema validation, block assembly, the turn/step loop (including tool failures and argument rejection), the built-in tools, the provider registry and config loading, the MiniMax request shape, `reasoning_content` handling, and tool calls split across chunks, and the full HTTP + SSE wire round trip against local mock servers for both the DeepSeek and OpenAI wire formats.

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
| Cordis plugin runtime, GUI, persistence, SDK | *not included* |

The wire protocol matches the harness's DeepSeek adapter: `POST {baseURL}/v1/messages` with an Anthropic-style Messages body, `x-api-key` authentication, and SSE streaming. The OpenAI adapter additionally covers the Chat Completions protocol the harness does not implement.

## Limitations

- **Two protocols.** The DeepSeek Messages API and the OpenAI Chat Completions API. Other protocols need a new adapter.
- **No persistence.** The session log lives in memory and is lost on exit; `--log` prints it for inspection.
- **No sandbox.** The `bash` tool runs commands directly; the file tools are confined to the workspace root, but the shell is not.
- **No compaction or context management.** Long conversations are sent in full.
- **No approval gate.** Every tool call runs without asking.
