/**
 * Provider configuration: reads a `providers.json` file that declares custom
 * model API endpoints, and registers each one with the provider registry.
 *
 * The file format:
 *
 * ```json
 * {
 *   "providers": {
 *     "my-llm": {
 *       "kind": "openai",
 *       "baseURL": "https://my-llm.example.com/v1",
 *       "apiKey": "${MY_LLM_API_KEY}",
 *       "headers": { "x-tenant": "team-a" }
 *     },
 *     "local": {
 *       "kind": "openai",
 *       "baseURL": "http://127.0.0.1:11434/v1",
 *       "apiKey": "not-needed"
 *     }
 *   }
 * }
 * ```
 *
 * A `${VAR}` placeholder in any string value reads the environment variable
 * `VAR`, so a secret never has to live in the file.
 *
 * @module mini-agent/core/config
 */

import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { homedir } from 'node:os'
import { ProviderRegistry } from './providers.ts'
import type { ProviderSettings } from './providers.ts'
import { DeepSeekAdapter } from '../llm/deepseek.ts'
import { OpenAiAdapter } from '../llm/openai.ts'

/** The configuration file name looked up in each candidate directory. */
const CONFIG_FILE_NAME = 'providers.json'

/**
 * Expand every `${VAR}` placeholder in one settings object.
 * @param settings - the raw settings.
 * @returns the settings with placeholders resolved.
 */
export function expandEnv(settings: ProviderSettings): ProviderSettings {
  const resolved: ProviderSettings = {}
  for (const [key, value] of Object.entries(settings)) {
    resolved[key] = typeof value === 'string' ? value.replace(/\$\{(\w+)\}/gu, (_match, name: string) => {
      return process.env[name] ?? ''
    }) : value
  }
  return resolved
}

/**
 * Build the adapter for one provider entry.
 * @param kind - the adapter kind.
 * @param settings - the provider settings.
 * @returns the adapter.
 */
export function createAdapter(kind: string, settings: ProviderSettings): { provider: string; adapter: import('./llm.ts').LlmAdapter } {
  const resolved = expandEnv(settings)
  switch (kind) {
    case 'deepseek': {
      const adapter = new DeepSeekAdapter({
        ...resolved.apiKey === undefined ? {} : { apiKey: String(resolved.apiKey) },
        ...resolved.baseURL === undefined ? {} : { baseURL: String(resolved.baseURL) },
        ...resolved.provider === undefined ? {} : { provider: String(resolved.provider) },
      })
      return { provider: adapter.provider, adapter }
    }
    case 'openai': {
      const adapter = new OpenAiAdapter({
        ...resolved.apiKey === undefined ? {} : { apiKey: String(resolved.apiKey) },
        ...resolved.baseURL === undefined ? {} : { baseURL: String(resolved.baseURL) },
        ...resolved.provider === undefined ? {} : { provider: String(resolved.provider) },
        ...resolved.headers === undefined ? {} : { headers: resolved.headers as Record<string, string> },
        ...resolved.extraBody === undefined ? {} : { extraBody: resolved.extraBody as Record<string, unknown> },
        ...resolved.useMaxCompletionTokens === undefined
          ? {}
          : { useMaxCompletionTokens: resolved.useMaxCompletionTokens === true },
      })
      return { provider: adapter.provider, adapter }
    }
    default:
      throw new Error(`unknown provider kind "${kind}"; supported kinds: deepseek, openai`)
  }
}

/**
 * Build the adapter for one provider entry.
 * @param kind - the adapter kind.
 * @param settings - the provider settings.
 * @returns the adapter.
 */
export function createAdapterFromSettings(kind: string, settings: ProviderSettings): import('./llm.ts').LlmAdapter {
  return createAdapter(kind, settings).adapter
}

/**
 * Register one provider entry with the registry.
 * @param registry - the registry to add to.
 * @param name - the provider name.
 * @param entry - the raw entry from the configuration file.
 */
export function registerProvider(registry: ProviderRegistry, name: string, entry: Record<string, unknown>): void {
  const kind = String(entry.kind ?? 'openai')
  const { provider, adapter } = createAdapter(kind, entry)
  // A config file redefines a built-in route on purpose.
  registry.replace(name, kind, { ...entry, provider: adapter.provider }, () => adapter)
}

/**
 * Load the provider configuration and register every declared provider.
 *
 * The file is looked up in the workspace, then the user's home directory, then
 * `$MINI_AGENT_CONFIG`. A missing file is not an error: the built-in providers
 * are always registered.
 * @param registry - the registry to populate.
 * @param cwd - the workspace directory searched first.
 * @returns the path of the file that was loaded, or undefined when none was found.
 */
export async function loadProviders(registry: ProviderRegistry, cwd: string): Promise<string | undefined> {
  const candidates = [
    process.env.MINI_AGENT_CONFIG,
    resolve(cwd, CONFIG_FILE_NAME),
    resolve(homedir(), `.${CONFIG_FILE_NAME}`),
    resolve(homedir(), `.config/mini-agent/${CONFIG_FILE_NAME}`),
  ].filter((candidate): candidate is string => candidate !== undefined && candidate.length > 0)

  for (const candidate of candidates) {
    let raw: string
    try {
      raw = await readFile(candidate, 'utf8')
    } catch (_missingFile) {
      continue
    }
    let parsed: { providers?: Record<string, Record<string, unknown>> }
    try {
      parsed = JSON.parse(raw) as { providers?: Record<string, Record<string, unknown>> }
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : String(error)
      throw new Error(`provider config "${candidate}" is not valid JSON: ${message}`)
    }
    for (const [name, entry] of Object.entries(parsed.providers ?? {})) {
      registerProvider(registry, name, entry)
    }
    return candidate
  }
  return undefined
}
