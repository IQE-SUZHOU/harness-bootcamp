/**
 * Provider registry: the seam that lets a custom model API join the agent
 * without touching the core loop.
 *
 * A provider is a named entry that knows how to build an {@link LlmAdapter}
 * from its own settings. The registry resolves a provider name into an
 * adapter, so the CLI can select `--provider openai` without the core
 * importing every adapter.
 *
 * @module mini-agent/core/providers
 */

import type { LlmAdapter } from './llm.ts'

/** The settings of one provider, as read from configuration. */
export type ProviderSettings = Record<string, unknown>

/** One provider route the agent can talk to. */
export interface ProviderDefinition {
  /** The provider name used by `--provider` and by `AgentOptions.provider`. */
  name: string
  /** Which adapter implementation serves this provider. */
  kind: string
  /** The provider-specific settings passed to the adapter factory. */
  settings: ProviderSettings
}

/** One registered provider entry. */
interface RegisteredProvider {
  definition: ProviderDefinition
  /** Build the adapter for this provider. */
  create: (settings: ProviderSettings) => LlmAdapter
}

/**
 * A registry of provider routes.
 *
 * The registry owns one map of providers. Registering the same name twice
 * fails, so a configuration typo cannot silently shadow a working provider.
 */
export class ProviderRegistry {
  private readonly providers = new Map<string, RegisteredProvider>()

  /**
   * Register one provider route.
   *
   * A name that is already registered fails, so a configuration typo cannot
   * silently shadow a working provider. Use {@link replace} to redefine a
   * route on purpose.
   * @param name - the provider name.
   * @param kind - the adapter kind that serves it.
   * @param settings - the provider-specific settings.
   * @param create - the factory that builds the adapter.
   * @returns the disposer that unregisters the provider.
   */
  register(
    name: string,
    kind: string,
    settings: ProviderSettings,
    create: (settings: ProviderSettings) => LlmAdapter,
  ): () => void {
    if (this.providers.has(name)) {
      throw new Error(`provider "${name}" is already registered`)
    }
    this.providers.set(name, { definition: { name, kind, settings }, create })
    return () => { this.providers.delete(name) }
  }

  /**
   * Define one provider route, replacing any route of the same name.
   * @param name - the provider name.
   * @param kind - the adapter kind that serves it.
   * @param settings - the provider-specific settings.
   * @param create - the factory that builds the adapter.
   */
  replace(
    name: string,
    kind: string,
    settings: ProviderSettings,
    create: (settings: ProviderSettings) => LlmAdapter,
  ): void {
    this.providers.set(name, { definition: { name, kind, settings }, create })
  }

  /**
   * Build the adapter for one registered provider.
   * @param name - the provider name.
   * @returns the adapter for that provider.
   */
  create(name: string): LlmAdapter {
    const registered = this.providers.get(name)
    if (registered === undefined) {
      const known = [...this.providers.keys()].join(', ') || '(none)'
      throw new Error(`unknown provider "${name}"; registered providers: ${known}`)
    }
    return registered.create(registered.definition.settings)
  }

  /** The names of every registered provider. */
  names(): string[] {
    return [...this.providers.keys()]
  }

  /**
   * The settings of one registered provider, including its adapter kind.
   *
   * The kind belongs to the returned map so a caller that rebuilds the route
   * — as the CLI does when applying an override — cannot lose the adapter
   * type and silently build a different protocol.
   * @param name - the provider name.
   * @returns the settings and kind, or undefined when unregistered.
   */
  settingsOf(name: string): (ProviderSettings & { kind: string }) | undefined {
    const registered = this.providers.get(name)
    if (registered === undefined) return undefined
    return { ...registered.definition.settings, kind: registered.definition.kind }
  }
}
