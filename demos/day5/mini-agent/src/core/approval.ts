/**
 * Human approval gate.
 *
 * Some work may only proceed after a human says so. The gate is
 * **fail-closed**: with no approver configured, or with an approver that
 * throws, the gate refuses. The agent cannot approve its own work — the
 * approval comes from outside the model.
 *
 * A granted approval is recorded as a token, so a later verifier can check
 * that the work really was approved rather than merely claiming it was.
 *
 * @module mini-agent/core/approval
 */

import { randomBytes } from 'node:crypto'

/** How a gate answered one request. */
export type ApprovalDecision =
  | { kind: 'approved'; token: string }
  | { kind: 'rejected'; reason: string }
  | { kind: 'cancelled'; reason: string }
  | { kind: 'unavailable'; reason: string }

/** The question the gate asks. */
export interface ApprovalRequest {
  /** What the agent wants to do. */
  action: string
  /** Why it wants to do it. */
  reason: string
}

/** A function that answers an approval request. */
export type Approver = (request: ApprovalRequest) => Promise<ApprovalDecision> | ApprovalDecision

/** The prefix of a granted approval token. */
export const APPROVAL_TOKEN_PREFIX = 'APPROVED-BY-HUMAN-'

/**
 * Generate an approval token.
 *
 * The token is random, so a forged one cannot be predicted.
 * @returns the token.
 */
export function generateApprovalToken(): string {
  return `${APPROVAL_TOKEN_PREFIX}${randomBytes(8).toString('hex')}`
}

/**
 * A human approval gate.
 *
 * The gate is fail-closed: an approver that throws is treated as
 * `unavailable`, and the request is refused.
 */
export class ApprovalGate {
  /** The approver, when one is configured. */
  private readonly approver: Approver | undefined
  /** The tokens this gate granted, newest last. */
  private readonly granted: string[] = []

  constructor(approver?: Approver) {
    this.approver = approver
  }

  /**
   * Ask for approval.
   *
   * A missing approver, a throwing approver, and an explicit rejection all
   * refuse the request; only an explicit approval grants it.
   * @param request - the question to ask.
   * @returns the decision.
   */
  async request(request: ApprovalRequest): Promise<ApprovalDecision> {
    if (this.approver === undefined) {
      return { kind: 'unavailable', reason: 'no approver is configured' }
    }
    let decision: ApprovalDecision
    try {
      decision = await this.approver(request)
    } catch (error: unknown) {
      // Fail closed: an approver that throws must not unlock the action.
      const reason = error instanceof Error ? error.message : String(error)
      return { kind: 'unavailable', reason: `the approver failed: ${reason}` }
    }
    if (decision.kind === 'approved') {
      // A granted approval always carries a token, even when the approver
      // did not supply one, so a verifier can always check for one.
      const token = decision.token.length > 0 ? decision.token : generateApprovalToken()
      this.granted.push(token)
      return { kind: 'approved', token }
    }
    return decision
  }

  /** The tokens this gate granted. */
  get grantedTokens(): readonly string[] {
    return this.granted
  }

  /**
   * Whether a token came from this gate.
   * @param token - the token to check.
   * @returns whether the token was granted here.
   */
  hasToken(token: string): boolean {
    return this.granted.includes(token)
  }
}

/**
 * Check an approval token's shape.
 *
 * The check is deliberately weak: it proves a token *looks* like an approval,
 * not that a human issued it. Use {@link ApprovalGate.hasToken} for that.
 * @param token - the token to check.
 * @returns whether the token has the expected shape.
 */
export function isApprovalToken(token: string): boolean {
  return token.startsWith(APPROVAL_TOKEN_PREFIX) && token.length > APPROVAL_TOKEN_PREFIX.length
}
