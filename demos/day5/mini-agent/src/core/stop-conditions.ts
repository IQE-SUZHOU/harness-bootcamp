/**
 * Stop conditions: the limits that let a turn brake itself.
 *
 * Without them the agent loop runs until the model stops asking for tools, so
 * a task that sends the model in circles never ends. A stop condition is
 * checked at every step boundary; when one trips, the turn ends with an
 * explicit reason instead of continuing.
 *
 * The model mirrors the Harness's own limits: a cap on rounds, a deadline,
 * and a budget — each reported with the reason it tripped, never silently.
 *
 * @module mini-agent/core/stop-conditions
 */

/** Which limit tripped. */
export type StopReasonKind = 'max-steps' | 'timeout' | 'max-tokens'

/** Why the loop stopped, with the limit that tripped. */
export interface StopReason {
  /** The limit that tripped. */
  kind: StopReasonKind
  /** A human-readable explanation naming the limit and its value. */
  message: string
}

/** The configured limits for one agent. */
export interface StopConditionsConfig {
  /** Maximum model requests in one turn. */
  maxSteps?: number
  /** Maximum wall-clock duration of one turn, in milliseconds. */
  timeoutMs?: number
  /** Maximum total tokens consumed by one turn. */
  maxTotalTokens?: number
}

/** The limits and the counters that decide whether the turn may continue. */
export interface StopConditions {
  /**
   * Whether the turn may take another step.
   * @param steps - the number of model requests made so far.
   * @param usage - the tokens consumed by the turn so far.
   * @param elapsedMs - the milliseconds elapsed since the turn started.
   * @returns the reason the turn must stop, or undefined when it may continue.
   */
  check(steps: number, usage: number, elapsedMs: number): StopReason | undefined
  /**
   * The token total the turn has consumed.
   * @param inputTokens - the input tokens of one model response.
   * @param outputTokens - the output tokens of one model response.
   */
  addUsage(inputTokens: number, outputTokens: number): void
  /** The tokens consumed so far. */
  readonly totalTokens: number
}

/**
 * Validate one configured limit.
 * @param name - the limit name.
 * @param value - the configured value.
 * @returns the validated value.
 */
function positiveLimit(name: string, value: number | undefined): number | undefined {
  if (value === undefined) return undefined
  if (!Number.isFinite(value) || value <= 0) {
    throw new TypeError(`stop condition "${name}" must be a positive finite number`)
  }
  return value
}

/**
 * Build the stop conditions for one agent.
 *
 * An empty configuration yields conditions that never trip, which keeps the
 * unlimited behavior available without a special case in the loop.
 * @param config - the configured limits.
 * @returns the stop conditions.
 */
export function createStopConditions(config: StopConditionsConfig = {}): StopConditions {
  const maxSteps = positiveLimit('maxSteps', config.maxSteps)
  const timeoutMs = positiveLimit('timeoutMs', config.timeoutMs)
  const maxTotalTokens = positiveLimit('maxTotalTokens', config.maxTotalTokens)
  let totalTokens = 0

  return {
    get totalTokens(): number {
      return totalTokens
    },
    addUsage(inputTokens: number, outputTokens: number): void {
      totalTokens += inputTokens + outputTokens
    },
    check(steps: number, usage: number, elapsedMs: number): StopReason | undefined {
      // The step cap is checked first: it is the cheapest and the most
      // predictable brake on a runaway loop.
      if (maxSteps !== undefined && steps >= maxSteps) {
        return {
          kind: 'max-steps',
          message: `the turn reached its limit of ${maxSteps} step${maxSteps === 1 ? '' : 's'}`,
        }
      }
      if (timeoutMs !== undefined && elapsedMs >= timeoutMs) {
        return {
          kind: 'timeout',
          message: `the turn reached its time limit of ${timeoutMs}ms`,
        }
      }
      if (maxTotalTokens !== undefined && usage >= maxTotalTokens) {
        return {
          kind: 'max-tokens',
          message: `the turn reached its token limit of ${maxTotalTokens} tokens`,
        }
      }
      return undefined
    },
  }
}
