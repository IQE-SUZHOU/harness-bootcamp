# Adding a custom model API

There are three ways to point the mini agent at a different model, from easiest to most flexible.

---

## 1. Command-line flags (no file, no code)

Use the built-in `openai` route with an endpoint override. This works with any
service that speaks the **OpenAI Chat Completions** protocol:

```sh
node --experimental-strip-types src/cli/main.ts \
  --provider openai \
  --base-url https://api.moonshot.cn/v1 \
  --api-key $MOONSHOT_API_KEY \
  --model kimi-k2-0905-preview \
  "列出当前目录的文件"
```

`--base-url` and `--api-key` override whatever the provider route declares.

---

## 2. A `providers.json` file (recommended)

Declare each endpoint once, then select it by name. Create `providers.json` in
your workspace, or in `~/.config/mini-agent/providers.json`, or point
`$MINI_AGENT_CONFIG` at it.

```json
{
  "providers": {
    "my-llm": {
      "kind": "openai",
      "baseURL": "https://my-llm.example.com/v1",
      "apiKey": "${MY_LLM_API_KEY}",
      "headers": {
        "x-tenant": "team-a"
      }
    },
    "local": {
      "kind": "openai",
      "baseURL": "http://127.0.0.1:11434/v1",
      "apiKey": "not-needed"
    },
    "deepseek-eu": {
      "kind": "deepseek",
      "baseURL": "https://api.deepseek.com",
      "apiKey": "${DEEPSEEK_API_KEY}"
    }
  }
}
```

Then:

```sh
node --experimental-strip-types src/cli/main.ts --provider my-llm --model my-model "task"
node --experimental-strip-types src/cli/main.ts --list-providers
```

**`${VAR}` placeholders** in any string value are replaced with the
environment variable `VAR`, so secrets stay out of the file. An unset
variable expands to an empty string, and the CLI then reports a missing key.

### Fields

| Field | Meaning |
| --- | --- |
| `kind` | `openai` (Chat Completions) or `deepseek` (Messages API). Default `openai`. |
| `baseURL` | Endpoint root. `openai` appends `/chat/completions`; `deepseek` appends `/v1/messages`. |
| `apiKey` | The key. `${VAR}` placeholders are expanded. |
| `headers` | Extra headers merged into every request. |
| `provider` | Override the provider route key reported to the agent. Optional. |
| `extraBody` | Provider-specific request fields merged into every body. Optional. |
| `useMaxCompletionTokens` | Send `max_completion_tokens` instead of `max_tokens`. Optional. |

### Search order

1. `$MINI_AGENT_CONFIG` (exact path)
2. `<workspace>/providers.json`
3. `~/.providers.json`
4. `~/.config/mini-agent/providers.json`

The first file found wins. A file that exists but is malformed is an error —
the agent refuses to start rather than silently using the wrong endpoint.

---

## MiniMax

MiniMax speaks the **OpenAI Chat Completions** protocol with a Bearer token,
so the built-in `openai` route serves it. Two MiniMax routes are pre-registered:

| Route | Endpoint | Platform |
| --- | --- | --- |
| `minimax` | `https://api.minimaxi.com/v1` | China |
| `minimax-intl` | `https://api.minimax.io/v1` | International |

```sh
export MINIMAX_API_KEY=你的key
node --experimental-strip-types src/cli/main.ts \
  --provider minimax --model MiniMax-M3.1-Flash "task"
```

The route resolves to the China endpoint by default, sends
`max_completion_tokens` instead of `max_tokens`, and reads the
`reasoning_content` field that carries the model's thinking.

### ⚠️ The two platforms issue separate keys

A key created on the China platform is **rejected** by the international one,
and the reverse. The symptom is a `401` with error code `2049`:

```
{"type":"error","error":{"type":"authorized_error",
 "message":"invalid api key (2049)","http_code":"401"}}
```

An error code of `1004` instead means the key was never sent at all — that is
a client-side problem, not a key problem.

Pick the route that matches where the key was created, or set the endpoint
explicitly:

```sh
MINIMAX_BASE_URL=https://api.minimax.io/v1 \
  node --experimental-strip-types src/cli/main.ts --provider minimax --model MiniMax-M3 "task"
```

### Models

| Model | Notes |
| --- | --- |
| `MiniMax-M3.1-Flash` | 1M context, tunable thinking depth (`reasoning_effort`). Always thinks. |
| `MiniMax-M3` | 1M context. Thinking can be disabled. |

The `MiniMax-M2.x` families are retired and no longer work.

### Provider-specific fields

MiniMax ignores `temperature` (always 1) and `top_p` (always 0.95). Thinking
is controlled by fields the OpenAI schema does not define, so they go through
`extraBody`:

```json
{
  "providers": {
    "minimax": {
      "kind": "openai",
      "baseURL": "https://api.minimaxi.com/v1",
      "apiKey": "${MINIMAX_API_KEY}",
      "useMaxCompletionTokens": true,
      "extraBody": {
        "reasoning_effort": "max",
        "thinking": { "type": "adaptive" }
      }
    }
  }
}
```

| Field | Values | Notes |
| --- | --- | --- |
| `reasoning_effort` | `low`, `medium`, `high`, `xhigh`, `max` | `MiniMax-M3.1-Flash` only. Defaults to `max`. `none` returns 400. |
| `thinking` | `{ "type": "disabled" }` or `{ "type": "adaptive" }` | `MiniMax-M3` only. `M3.1-Flash` returns 400 on `disabled`. |
| `reasoning_split` | `true` / `false` | Separates thinking into `reasoning_content`. `false` is unsupported on `M3.1-Flash`. |
| `service_tier` | `standard`, `priority` | Priority admission at 1.5× price. Unsupported on `M3.1-Flash`. |

---

## 3. A new adapter (any protocol)

When the provider does **not** speak the OpenAI or DeepSeek protocol, write an
adapter. An adapter is one class with a `provider` field and a `stream` method
that yields `StreamChunk`s.

```ts
// src/llm/my-provider.ts
import type { LlmAdapter } from '../core/llm.ts'
import type { GenerateOptions, StreamChunk } from '../core/types.ts'

export class MyProviderAdapter implements LlmAdapter {
  readonly provider = 'my-provider'

  constructor(private readonly apiKey: string) {}

  async *stream(options: GenerateOptions): AsyncIterable<StreamChunk> {
    const response = await fetch('https://my-provider.example/v1/generate', {
      method: 'POST',
      headers: { authorization: `Bearer ${this.apiKey}` },
      body: JSON.stringify({ model: options.model, prompt: options.messages }),
      signal: options.signal,
    })
    // ... decode the response and yield chunks
    yield { type: 'block-start', index: 0, blockType: 'text' }
    yield { type: 'text-delta', index: 0, text: 'hello' }
    yield { type: 'block-end', index: 0, block: { type: 'text', text: 'hello' } }
    yield { type: 'finish', reason: { kind: 'stop' } }
  }
}
```

Then register it. The cleanest place is `src/core/config.ts`, in the
`createAdapter` switch:

```ts
case 'my-provider': {
  const adapter = new MyProviderAdapter(String(resolved.apiKey ?? ''))
  return { provider: adapter.provider, adapter }
}
```

and declare it in `providers.json`:

```json
{ "providers": { "mine": { "kind": "my-provider", "apiKey": "${MY_KEY}" } } }
```

### The chunk protocol

The adapter must translate the provider's wire format into these chunks:

| Chunk | Meaning |
| --- | --- |
| `block-start` | Opens a block at `index` with `blockType` `text`, `reasoning`, or `tool-call`. |
| `text-delta` | Appends visible text to the block at `index`. |
| `reasoning-delta` | Appends reasoning text to the block at `index`. |
| `tool-call-delta` | Carries the tool `id`, optional `name`, and a fragment of `argumentsDelta`. |
| `block-end` | Closes the block at `index` with its complete `block`. |
| `usage` | Reports token counts. Optional. |
| `finish` | The terminal frame. Required exactly once. |

Rules the agent loop relies on:

- **Every `tool-call` block needs an `id`.** The agent matches the tool result
  back to the call by that id; without it, the result is dropped.
- **`argumentsDelta` fragments concatenate into the raw JSON arguments
  string.** The agent parses it once the block closes.
- **The `finish` frame must come last.** A stream that ends without one is
  treated as a failure.
- **`finish.reason.kind === 'tool-calls'`** tells the loop to execute the
  requested tools and request the model again. `stop` ends the turn.

`BlockAssembler` (in `src/core/llm.ts`) reassembles the chunks into content
blocks, so an adapter does not need to buffer anything itself.

---

## Using the agent as a library

The provider registry is exported, so you can build an agent with any adapter
without touching the CLI:

```ts
import { Agent, ToolRegistry, ProviderRegistry, createBuiltinTools } from './src/index.ts'
import { MyProviderAdapter } from './src/llm/my-provider.ts'

const registry = new ToolRegistry()
for (const tool of createBuiltinTools(process.cwd())) registry.register(tool)

const adapter = new MyProviderAdapter(process.env.MY_KEY!)
const agent = new Agent(adapter, registry, {
  provider: adapter.provider,
  model: 'my-model',
  systemPrompt: 'You are a helpful assistant.',
  onText: (text) => process.stdout.write(text),
})

await agent.run('What is 2 + 2?')
```

---

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| `unknown provider "x"` | The name is not in `providers.json` and is not a built-in. Run `--list-providers`. |
| `no API key` | The key is missing from the environment, `--api-key`, and the config entry. |
| `HTTP 401` with code `1004` | The key was never sent. Check `kind` and the header the endpoint expects. |
| `HTTP 401` with code `2049` | The key was sent but rejected. On MiniMax this means the key belongs to the other regional platform. |
| `HTTP 404` | The base URL is wrong. For `openai`, give the root ending in `/v1`; the adapter appends `/chat/completions`. |
| `HTTP 400` on `thinking.type="disabled"` | `MiniMax-M3.1-Flash` always thinks and rejects a disabled request. Use `MiniMax-M3` instead. |
| `HTTP 400` on `reasoning_effort: "none"` | MiniMax does not accept `none`; use `low` through `max`. |
| Empty content with `finish_reason: "length"` | The output cap was too small. Thinking tokens count toward it; raise the cap or use `max_completion_tokens`. |
| The model answers but never calls tools | The provider did not send `finish_reason: "tool_calls"`, or the tool schemas are malformed. |
| `stream ended before the finish frame` | The provider closed the connection early, or the endpoint is not OpenAI-compatible. |
| Tool calls appear but no result follows | The tool-call block carried no `id`. |
