/**
 * Command-line entry point for the mini agent.
 *
 * Usage:
 *   mini-agent "list the files in this directory"
 *   mini-agent --interactive
 *
 * @module mini-agent/cli/main
 */

import { createInterface } from 'node:readline/promises'
import { resolve } from 'node:path'
import { Agent } from '../core/agent.ts'
import { ToolRegistry } from '../core/tools.ts'
import { ProviderRegistry } from '../core/providers.ts'
import { loadProviders, createAdapterFromSettings, expandEnv } from '../core/config.ts'
import { DEFAULT_MODEL } from '../llm/deepseek.ts'
import { createBuiltinTools } from '../tools/builtin.ts'

/** The default system prompt for the mini agent. */
const DEFAULT_SYSTEM_PROMPT = `You are a concise coding assistant working in a local workspace.

Use the provided tools to inspect and modify files instead of guessing. Prefer reading a file before editing it.
When you have finished the task, answer with a short summary of what you did.`

/** Parsed command-line options. */
interface CliOptions {
  /** The one-shot task text, when one was given. */
  task: string | undefined
  /** Whether to read tasks from stdin instead. */
  interactive: boolean
  /** The model id to use. */
  model: string
  /** The workspace root. */
  cwd: string
  /** The API key. */
  apiKey: string
  /** The endpoint root. */
  baseURL: string | undefined
  /** The provider name to use. */
  provider: string
  /** The sampling temperature. */
  temperature: number | undefined
  /** Whether to print the session log at the end. */
  showLog: boolean
  /** Whether to list the registered providers and exit. */
  listProviders: boolean
}

/**
 * Parse the command-line arguments.
 * @param argv - the raw arguments after the script path.
 * @returns the parsed options.
 */
export function parseArgs(argv: readonly string[]): CliOptions {
  const options: CliOptions = {
    task: undefined,
    interactive: false,
    model: process.env.MINI_AGENT_MODEL ?? DEFAULT_MODEL,
    cwd: process.cwd(),
    apiKey: process.env.DEEPSEEK_API_KEY ?? '',
    baseURL: process.env.DEEPSEEK_BASE_URL,
    provider: process.env.MINI_AGENT_PROVIDER ?? 'deepseek',
    temperature: undefined,
    showLog: false,
    listProviders: false,
  }
  const positional: string[] = []
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index]
    switch (arg) {
      case '-i':
      case '--interactive':
        options.interactive = true
        break
      case '--model':
        options.model = argv[++index] ?? options.model
        break
      case '--cwd':
        options.cwd = resolve(argv[++index] ?? options.cwd)
        break
      case '--base-url':
        options.baseURL = argv[++index]
        break
      case '--provider':
        options.provider = argv[++index] ?? options.provider
        break
      case '--temperature':
        options.temperature = Number(argv[++index])
        break
      case '--api-key':
        options.apiKey = argv[++index] ?? options.apiKey
        break
      case '--log':
        options.showLog = true
        break
      case '--list-providers':
        options.listProviders = true
        break
      case '-h':
      case '--help':
        printUsage()
        process.exit(0)
        break
      default:
        if (arg.startsWith('-')) {
          console.error(`unknown option "${arg}"`)
          printUsage()
          process.exit(2)
        }
        positional.push(arg)
    }
  }
  if (positional.length > 0) options.task = positional.join(' ')
  return options
}

/** Print the usage text. */
function printUsage(): void {
  console.log(`mini-agent — a minimal local coding agent

Usage:
  mini-agent [options] "task"     Run one task and exit
  mini-agent [options] -i         Read tasks from stdin, one per line

Options:
  -i, --interactive     Read tasks from stdin interactively
      --provider <name> Provider route to use (default: deepseek, or MINI_AGENT_PROVIDER)
      --model <id>      Model id (default: ${DEFAULT_MODEL}, or MINI_AGENT_MODEL)
      --cwd <path>      Workspace root (default: current directory)
      --base-url <url>  API endpoint (default: https://api.deepseek.com)
      --api-key <key>   API key (default: $DEEPSEEK_API_KEY)
      --temperature <n> Sampling temperature
      --log             Print the session event log when finished
      --list-providers  List the registered provider routes and exit
  -h, --help            Show this help

Environment:
  DEEPSEEK_API_KEY      API key used for the request
  DEEPSEEK_BASE_URL     Optional endpoint override
  MINI_AGENT_PROVIDER   Optional provider route override
  MINI_AGENT_MODEL      Optional model override
  MINI_AGENT_CONFIG     Optional path to a providers.json file`)
}

/**
 * Build the provider registry from the built-in routes and the config file.
 * @param cwd - the workspace directory searched for the config file.
 * @returns the registry and the path of the config file that was loaded.
 */
async function buildProviders(cwd: string): Promise<{ registry: ProviderRegistry; configPath: string | undefined }> {
  const registry = new ProviderRegistry()
  registry.register('deepseek', 'deepseek', {
    apiKey: process.env.DEEPSEEK_API_KEY ?? '',
    ...process.env.DEEPSEEK_BASE_URL === undefined ? {} : { baseURL: process.env.DEEPSEEK_BASE_URL },
  }, (settings) => createAdapterFromSettings('deepseek', settings))
  registry.register('openai', 'openai', {
    apiKey: process.env.OPENAI_API_KEY ?? '',
    ...process.env.OPENAI_BASE_URL === undefined ? {} : { baseURL: process.env.OPENAI_BASE_URL },
  }, (settings) => createAdapterFromSettings('openai', settings))
  // MiniMax speaks the OpenAI Chat Completions protocol with a Bearer token.
  // Its models ignore `temperature`, and `max_completion_tokens` is the field
  // its own documentation recommends for new integrations.
  //
  // The two regional platforms issue separate keys: a key from the China
  // platform is rejected by the international one and the reverse, so the
  // endpoint must match where the key was created.
  registry.register('minimax', 'openai', {
    apiKey: process.env.MINIMAX_API_KEY ?? '',
    baseURL: process.env.MINIMAX_BASE_URL ?? 'https://api.minimaxi.com/v1',
    useMaxCompletionTokens: true,
    ...process.env.MINIMAX_REASONING_EFFORT === undefined
      ? {}
      : { extraBody: { reasoning_effort: process.env.MINIMAX_REASONING_EFFORT } },
  }, (settings) => createAdapterFromSettings('openai', settings))
  // The international platform issues separate keys from the China one.
  registry.register('minimax-intl', 'openai', {
    apiKey: process.env.MINIMAX_API_KEY ?? '',
    baseURL: process.env.MINIMAX_BASE_URL ?? 'https://api.minimax.io/v1',
    useMaxCompletionTokens: true,
    ...process.env.MINIMAX_REASONING_EFFORT === undefined
      ? {}
      : { extraBody: { reasoning_effort: process.env.MINIMAX_REASONING_EFFORT } },
  }, (settings) => createAdapterFromSettings('openai', settings))
  const configPath = await loadProviders(registry, cwd)
  return { registry, configPath }
}

/**
 * Run the mini agent.
 * @param argv - the raw arguments after the script path.
 * @returns the process exit code.
 */
export async function main(argv: readonly string[]): Promise<number> {
  const options = parseArgs(argv)
  const { registry, configPath } = await buildProviders(options.cwd)

  if (options.listProviders) {
    console.log('registered providers:')
    for (const name of registry.names()) {
      const settings = registry.settingsOf(name) ?? { kind: 'unknown' }
      const baseURL = typeof settings.baseURL === 'string' ? settings.baseURL : '(default)'
      console.log(`  ${name.padEnd(16)} kind: ${settings.kind.padEnd(9)} baseURL: ${baseURL}`)
    }
    if (configPath !== undefined) console.log(`\nconfig file: ${configPath}`)
    return 0
  }

  // A command-line endpoint and key override the provider's own settings.
  const configured = registry.settingsOf(options.provider)
  if (configured === undefined) {
    console.error(`unknown provider "${options.provider}"; registered providers: ${registry.names().join(', ')}`)
    return 1
  }
  const kind = configured.kind
  const overrides = {
    ...options.baseURL === undefined ? {} : { baseURL: options.baseURL },
    ...options.apiKey.length === 0 ? {} : { apiKey: options.apiKey },
  }
  registry.replace(options.provider, kind, { ...configured, ...overrides },
    (settings) => createAdapterFromSettings(kind, settings))

  // The key check expands placeholders, so a config entry that references an
  // unset environment variable is reported as missing rather than sent empty.
  const effectiveKey = options.apiKey.length > 0
    ? options.apiKey
    : String(expandEnv(configured).apiKey ?? '')
  if (effectiveKey.length === 0) {
    console.error('no API key: set DEEPSEEK_API_KEY, pass --api-key, or declare one in providers.json')
    return 1
  }

  const toolRegistry = new ToolRegistry()
  for (const tool of createBuiltinTools(options.cwd)) {
    toolRegistry.register(tool)
  }
  const adapter = registry.create(options.provider)
  let toolCallCount = 0
  const agent = new Agent(adapter, toolRegistry, {
    provider: adapter.provider,
    model: options.model,
    systemPrompt: DEFAULT_SYSTEM_PROMPT,
    ...options.temperature === undefined ? {} : { temperature: options.temperature },
    onText: (text) => { process.stdout.write(text) },
    onToolCall: (name, args) => {
      toolCallCount += 1
      console.error(`\n[tool ${toolCallCount}] ${name}(${JSON.stringify(args)})`)
    },
    onToolResult: (name, isError, text) => {
      const preview = text.length > 400 ? `${text.slice(0, 400)}...` : text
      console.error(`[tool result] ${name}${isError ? ' (error)' : ''}: ${preview}`)
    },
  })

  const runTask = async (task: string): Promise<void> => {
    console.error(`\n> ${task}`)
    const result = await agent.run(task)
    process.stdout.write('\n')
    if (result.reason.kind === 'error') {
      console.error(`turn failed: ${result.reason.message}`)
    }
  }

  if (options.task !== undefined) {
    await runTask(options.task)
  } else {
    const rl = createInterface({ input: process.stdin, output: process.stdout })
    for (;;) {
      const line = await rl.question('you> ')
      const task = line.trim()
      if (task.length === 0) continue
      if (task === 'exit' || task === 'quit') break
      await runTask(task)
    }
    rl.close()
  }

  if (options.showLog) {
    console.error('\n--- session log ---')
    for (const { seq, event } of agent.session.snapshot()) {
      console.error(`${seq}: ${JSON.stringify(event)}`)
    }
  }
  return 0
}

// Run when invoked directly.
if (process.argv[1] !== undefined && import.meta.url === `file://${process.argv[1]}`) {
  main(process.argv.slice(2)).then((code) => { process.exit(code) })
}
