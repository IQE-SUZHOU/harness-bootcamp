/**
 * Tool registry and definition helpers.
 *
 * A tool declares a JSON Schema for its arguments and an `execute` function.
 * The registry validates arguments before execution and converts a failure
 * into a model-facing error result rather than aborting the turn.
 *
 * @module mini-agent/core/tools
 */

import type { ToolSchema } from './types.ts'

/** One tool available to the model. */
export interface ToolDefinition {
  /** Unique tool name. */
  name: string
  /** Model-facing description. */
  description: string
  /** JSON Schema object for the arguments. */
  parameters: Record<string, unknown>
  /**
   * Run one accepted call.
   * @param args - validated arguments.
   * @param signal - cancellation signal for the call.
   * @returns the model-facing result text.
   */
  execute(args: Record<string, unknown>, signal: AbortSignal): Promise<string>
}

/** One registered tool plus its disposer. */
interface Registration {
  definition: ToolDefinition
  dispose: () => void
}

/** Registry of tools available to one agent. */
export class ToolRegistry {
  private readonly tools = new Map<string, Registration>()

  /**
   * Register one tool.
   * @param definition - the tool to register.
   * @returns the disposer that unregisters the tool.
   */
  register(definition: ToolDefinition): () => void {
    if (this.tools.has(definition.name)) {
      throw new Error(`tool "${definition.name}" is already registered`)
    }
    this.tools.set(definition.name, { definition, dispose: () => { this.tools.delete(definition.name) } })
    return () => { this.tools.delete(definition.name) }
  }

  /**
   * Look up one registered tool.
   * @param name - the tool name.
   * @returns the definition, or undefined when unregistered.
   */
  get(name: string): ToolDefinition | undefined {
    return this.tools.get(name)?.definition
  }

  /** The schemas of every registered tool, in registration order. */
  schemas(): ToolSchema[] {
    return [...this.tools.values()].map(({ definition }) => ({
      name: definition.name,
      description: definition.description,
      parameters: definition.parameters,
    }))
  }

  /** The names of every registered tool. */
  names(): string[] {
    return [...this.tools.keys()]
  }
}

/**
 * Validate one value against a JSON Schema subset: `type`, `required`,
 * `properties`, `enum`, and `additionalProperties`.
 *
 * @param schema - the JSON Schema to check against.
 * @param value - the value to validate.
 * @returns the list of violations; empty when the value conforms.
 */
export function validateAgainstSchema(schema: Record<string, unknown>, value: unknown): string[] {
  const violations: string[] = []
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    return ['arguments must be a JSON object']
  }
  const record = value as Record<string, unknown>
  const type = schema.type
  if (type === 'object') {
    const properties = (schema.properties ?? {}) as Record<string, { type?: string; enum?: unknown[] }>
    const required = (schema.required ?? []) as string[]
    for (const key of required) {
      if (!(key in record)) violations.push(`missing required property "${key}"`)
    }
    if (schema.additionalProperties === false) {
      for (const key of Object.keys(record)) {
        if (!(key in properties)) violations.push(`unexpected property "${key}"`)
      }
    }
    for (const [key, definition] of Object.entries(properties)) {
      if (!(key in record)) continue
      const actual = record[key]
      if (definition.type !== undefined && typeof actual !== definition.type) {
        violations.push(`property "${key}" must be of type ${definition.type}`)
        continue
      }
      if (definition.enum !== undefined && !definition.enum.includes(actual)) {
        violations.push(`property "${key}" must be one of ${definition.enum.map(item => JSON.stringify(item)).join(', ')}`)
      }
    }
  }
  return violations
}
