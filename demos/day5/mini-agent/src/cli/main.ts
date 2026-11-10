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
import { resolve, join } from 'node:path'
import { homedir } from 'node:os'
import { readFile } from 'node:fs/promises'
import { Agent } from '../core/agent.ts'
import { ToolRegistry } from '../core/tools.ts'
import { ProviderRegistry } from '../core/providers.ts'
import { loadProviders, createAdapterFromSettings, expandEnv } from '../core/config.ts'
import type { StopConditionsConfig } from '../core/stop-conditions.ts'
import type { PruneConfig } from '../core/prune.ts'
import { SessionRepository } from '../core/repository.ts'
import { SessionStore } from '../core/persistence.ts'
import { renderVerifyTable, verifyWorkspace } from '../core/verify.ts'
import type { VerifySpec } from '../core/verify.ts'
import { runWorkflow } from '../core/workflow.ts'
import type { WorkflowBranch } from '../core/workflow.ts'
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
  /** The limits that let a turn brake itself. */
  stopConditions: StopConditionsConfig
  /** The character budgets that prune tool results in the derived request. */
  prune: PruneConfig
  /** Whether to print the session log at the end. */
  showLog: boolean
  /** Whether to list the registered providers and exit. */
  listProviders: boolean
  /** The session id to persist under and resume. */
  sessionId: string | undefined
  /** The directory holding the persisted sessions. */
  storeRoot: string
  /** The Definition-of-Done spec file to verify the workspace against. */
  verifySpec: string | undefined
  /** The workflow spec file to run. */
  workflowSpec: string | undefined
  /** Whether to list the persisted sessions and exit. */
  listSessions: boolean
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
    stopConditions: {
      ...process.env.MINI_AGENT_MAX_STEPS === undefined ? {} : { maxSteps: Number(process.env.MINI_AGENT_MAX_STEPS) },
      ...process.env.MINI_AGENT_TIMEOUT_MS === undefined ? {} : { timeoutMs: Number(process.env.MINI_AGENT_TIMEOUT_MS) },
      ...process.env.MINI_AGENT_MAX_TOTAL_TOKENS === undefined
        ? {}
        : { maxTotalTokens: Number(process.env.MINI_AGENT_MAX_TOTAL_TOKENS) },
    },
    prune: {
      ...process.env.MINI_AGENT_PRUNE_THRESHOLD === undefined
        ? {}
        : { thresholdChars: Number(process.env.MINI_AGENT_PRUNE_THRESHOLD) },
      ...process.env.MINI_AGENT_PRUNE_HEAD === undefined
        ? {}
        : { headChars: Number(process.env.MINI_AGENT_PRUNE_HEAD) },
      ...process.env.MINI_AGENT_PRUNE_TAIL === undefined
        ? {}
        : { tailChars: Number(process.env.MINI_AGENT_PRUNE_TAIL) },
    },
    showLog: false,
    listProviders: false,
    sessionId: process.env.MINI_AGENT_SESSION_ID,
    storeRoot: process.env.MINI_AGENT_STORE ?? join(homedir(), '.mini-agent', 'sessions'),
    verifySpec: undefined,
    workflowSpec: undefined,
    listSessions: false,
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
      case '--max-steps':
        options.stopConditions.maxSteps = Number(argv[++index])
        break
      case '--timeout-ms':
        options.stopConditions.timeoutMs = Number(argv[++index])
        break
      case '--max-total-tokens':
        options.stopConditions.maxTotalTokens = Number(argv[++index])
        break
      case '--prune-threshold':
        options.prune.thresholdChars = Number(argv[++index])
        break
      case '--prune-head':
        options.prune.headChars = Number(argv[++index])
        break
      case '--prune-tail':
        options.prune.tailChars = Number(argv[++index])
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
      case '--session-id':
        options.sessionId = argv[++index]
        break
      case '--store':
        options.storeRoot = resolve(argv[++index] ?? options.storeRoot)
        break
      case '--verify':
        options.verifySpec = argv[++index]
        break
      case '--workflow':
        options.workflowSpec = argv[++index]
        break
      case '--list-sessions':
        options.listSessions = true
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
  mini-agent --verify <spec.json>  Verify a workspace against a DoD spec
  mini-agent --workflow <spec.json>  Run a fan-out / fan-in workflow

Options:
  -i, --interactive     Read tasks from stdin interactively
      --provider <name> Provider route to use (default: deepseek, or MINI_AGENT_PROVIDER)
      --model <id>      Model id (default: ${DEFAULT_MODEL}, or MINI_AGENT_MODEL)
      --cwd <path>      Workspace root (default: current directory)
      --base-url <url>  API endpoint (default: https://api.deepseek.com)
      --api-key <key>   API key (default: $DEEPSEEK_API_KEY)
      --session-id <id> Persist under this id and resume it when it exists
      --store <path>    Directory holding the persisted sessions
      --list-sessions   List the persisted sessions and exit
      --verify <file>   Verify the workspace against a DoD spec, then exit
      --workflow <file> Run a fan-out / fan-in workflow, then exit
      --temperature <n> Sampling temperature
      --max-steps <n>    Stop the turn after this many model requests
      --timeout-ms <n>   Stop the turn after this many milliseconds
      --max-total-tokens <n>  Stop the turn after this many tokens
      --prune-threshold <n>  Prune a tool result above this many characters
      --prune-head <n>   Keep this many leading characters when pruning
      --prune-tail <n>   Keep this many trailing characters when pruning
      --log             Print the session event log when finished
      --list-providers  List the registered provider routes and exit
  -h, --help            Show this help

Environment:
  DEEPSEEK_API_KEY      API key used for the request
  DEEPSEEK_BASE_URL     Optional endpoint override
  MINI_AGENT_PROVIDER   Optional provider route override
  MINI_AGENT_MODEL      Optional model override
  MINI_AGENT_CONFIG     Optional path to a providers.json file
  MINI_AGENT_MAX_STEPS  Optional step cap
  MINI_AGENT_TIMEOUT_MS Optional turn deadline in milliseconds
  MINI_AGENT_MAX_TOTAL_TOKENS  Optional token budget per turn
  MINI_AGENT_PRUNE_THRESHOLD   Optional tool-result pruning threshold
  MINI_AGENT_PRUNE_HEAD        Optional leading characters kept when pruning
  MINI_AGENT_PRUNE_TAIL        Optional trailing characters kept when pruning`)
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

  const store = new SessionStore({ root: options.storeRoot })
  const repository = new SessionRepository(store)

  if (options.listSessions) {
    const ids = await store.list()
    console.log('persisted sessions:')
    for (const id of ids) {
      const report = await repository.inspect(id)
      const open = report === undefined
        ? 0
        : report.interruptedToolCalls + report.interruptedSteps + report.interruptedTurns
      console.log(`  ${id.padEnd(24)} ${open === 0 ? 'clean' : `${open} interrupted record(s)`}`)
    }
    return 0
  }

  // The verifier is independent and non-LLM: it needs no provider, so it runs
  // before the API-key check.
  if (options.verifySpec !== undefined) {
    const spec = JSON.parse(await readFile(resolve(options.verifySpec), 'utf8')) as VerifySpec
    const result = await verifyWorkspace({ ...spec, workspace: spec.workspace ?? options.cwd })
    console.log(renderVerifyTable(result))
    console.log(`\n${result.allPassed ? 'all checks passed' : `failed: ${result.failed.join(', ')}`}`)
    return result.allPassed ? 0 : 1
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
  // A session id makes the run durable: the log is persisted, and the same
  // id resumes the stored log on the next run.
  const sessionId = options.sessionId ?? `session-${Date.now().toString(16)}`

  /** Run one task in a fresh child session, for a workflow branch. */
  const runBranch = async (task: string): Promise<string> => {
    const child = new Agent(adapter, toolRegistry, {
      provider: adapter.provider,
      model: options.model,
      systemPrompt: DEFAULT_SYSTEM_PROMPT,
      ...options.temperature === undefined ? {} : { temperature: options.temperature },
      stopConditions: options.stopConditions,
      prune: options.prune,
    }, `${sessionId}-branch-${Math.random().toString(16).slice(2, 8)}`)
    const result = await child.run(task)
    if (result.reason.kind === 'error') throw new Error(result.reason.message)
    return result.text
  }
  // A workflow runs its branches concurrently and summarizes the survivors.
  if (options.workflowSpec !== undefined) {
    const spec = JSON.parse(await readFile(resolve(options.workflowSpec), 'utf8')) as {
      branches: WorkflowBranch[]
      fanIn?: string
      limits?: { maxConcurrent?: number; maxTotal?: number; branchTimeoutMs?: number; runTimeoutMs?: number }
    }
    const outcome = await runWorkflow(spec.branches, async branch => await runBranch(branch.task), {
      ...spec.fanIn === undefined ? {} : { fanIn: spec.fanIn },
      summarize: async (task, survivors) => await runBranch(`${task}\n\n${survivors.join('\n')}`),
      ...spec.limits === undefined ? {} : { limits: spec.limits },
    })
    if (outcome.kind === 'failed') {
      console.error(`workflow failed (${outcome.fatal.kind}): ${outcome.fatal.message}`)
      return 1
    }
    console.log(JSON.stringify({ parts: outcome.parts, summary: outcome.summary }, null, 2))
    return 0
  }

  // A session id makes the run durable: the log is persisted, and the same
  // id resumes the stored log on the next run.
  const stored = await repository.resume(sessionId)
  if (stored !== undefined && stored.repair.closers.length > 0) {
    console.error(
      `[resume] repaired ${stored.repair.interruptedToolCalls} tool call(s), `
      + `${stored.repair.interruptedSteps} step(s), ${stored.repair.interruptedTurns} turn(s)`,
    )
  }

  const agent = new Agent(adapter, toolRegistry, {
    provider: adapter.provider,
    model: options.model,
    systemPrompt: DEFAULT_SYSTEM_PROMPT,
    ...options.temperature === undefined ? {} : { temperature: options.temperature },
    stopConditions: options.stopConditions,
    prune: options.prune,
    // A resumed session continues the stored history, so the model still sees
    // the earlier turns.
    ...stored === undefined ? {} : { session: stored.session },
    onText: (text) => { process.stdout.write(text) },
    onToolCall: (name, args) => {
      toolCallCount += 1
      console.error(`\n[tool ${toolCallCount}] ${name}(${JSON.stringify(args)})`)
    },
    onToolResult: (name, isError, text) => {
      const preview = text.length > 400 ? `${text.slice(0, 400)}...` : text
      console.error(`[tool result] ${name}${isError ? ' (error)' : ''}: ${preview}`)
    },
    onStopped: (kind, message) => {
      console.error(`\n[stopped] ${kind}: ${message}`)
    },
  }, sessionId)

  const runTask = async (task: string): Promise<void> => {
    console.error(`\n> ${task}`)
    const result = await agent.run(task)
    process.stdout.write('\n')
    if (result.reason.kind === 'error') {
      console.error(`turn failed: ${result.reason.message}`)
    }
    // The log is persisted after every turn, so a crash loses at most the
    // turn in flight, which the repair closes on the next run.
    await repository.save(agent.session, options.cwd)
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
