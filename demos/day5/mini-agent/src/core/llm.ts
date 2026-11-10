/**
 * LLM adapter interface and the streaming block assembler.
 *
 * An adapter owns one provider route and turns a {@link GenerateOptions} into
 * a stream of {@link StreamChunk}s. The agent loop never talks to a provider
 * directly; it only sees chunks.
 *
 * @module mini-agent/core/llm
 */

import type { ContentBlock, FinishReason, GenerateOptions, StreamChunk, TokenUsage } from './types.ts'

/** One provider route implementation. */
export interface LlmAdapter {
  /** The provider route key this adapter serves. */
  readonly provider: string
  /**
   * Stream one model response.
   * @param options - the complete request.
   * @returns the response chunk stream.
   */
  stream(options: GenerateOptions): AsyncIterable<StreamChunk>
}

/** Mutable assembly state for one open block. */
interface PartialBlock {
  blockType: 'text' | 'reasoning' | 'tool-call'
  text: string
  toolCallId?: string
  toolCallName?: string
  toolCallArguments: string
  /** Whether a `block-end` frame already closed this block. */
  closed: boolean
  /** The closed block, when one arrived. */
  final?: ContentBlock
}

/**
 * Assembles streamed chunks into complete content blocks.
 *
 * The assembler tolerates repeated `block-end` frames and deltas that arrive
 * after a block closed: the first close wins, so the streamed output and the
 * final assembled blocks always agree.
 */
export class BlockAssembler {
  private readonly partials = new Map<number, PartialBlock>()
  private readonly order: number[] = []
  private _usage: TokenUsage | undefined
  private _finish: FinishReason | undefined

  /**
   * Feed one chunk into the assembly state.
   * @param chunk - the next chunk, in stream order.
   */
  push(chunk: StreamChunk): void {
    switch (chunk.type) {
      case 'block-start': {
        if (this.partials.has(chunk.index)) return
        this.order.push(chunk.index)
        this.partials.set(chunk.index, {
          blockType: chunk.blockType,
          text: '',
          toolCallArguments: '',
          closed: false,
        })
        return
      }
      case 'text-delta':
      case 'reasoning-delta': {
        const partial = this.ensure(chunk.index, chunk.type === 'text-delta' ? 'text' : 'reasoning')
        if (partial.closed) return
        partial.text += chunk.text
        return
      }
      case 'tool-call-delta': {
        const partial = this.ensure(chunk.index, 'tool-call')
        if (partial.closed) return
        partial.toolCallId = chunk.id
        if (chunk.name) partial.toolCallName = chunk.name
        partial.toolCallArguments += chunk.argumentsDelta
        return
      }
      case 'block-end': {
        const partial = this.ensure(chunk.index, chunk.block.type === 'text'
          ? 'text'
          : chunk.block.type === 'reasoning'
            ? 'reasoning'
            : 'tool-call')
        if (partial.closed) return
        partial.closed = true
        partial.final = chunk.block
        return
      }
      case 'usage':
        this._usage = chunk.usage
        return
      case 'finish':
        this._finish = chunk.reason
        return
      default:
        return
    }
  }

  /** Get or create the partial state for one block index. */
  private ensure(index: number, blockType: PartialBlock['blockType']): PartialBlock {
    let partial = this.partials.get(index)
    if (partial === undefined) {
      partial = { blockType, text: '', toolCallArguments: '', closed: false }
      this.partials.set(index, partial)
      this.order.push(index)
    }
    return partial
  }

  /** The assembled blocks, in the order their blocks opened. */
  blocks(): ContentBlock[] {
    const blocks: ContentBlock[] = []
    for (const index of this.order) {
      const partial = this.partials.get(index)
      if (partial === undefined) continue
      if (partial.final !== undefined) {
        blocks.push(partial.final)
        continue
      }
      // A block without a close frame is still usable when it carries content.
      switch (partial.blockType) {
        case 'text':
          if (partial.text.length > 0) blocks.push({ type: 'text', text: partial.text })
          break
        case 'reasoning':
          if (partial.text.length > 0) blocks.push({ type: 'reasoning', text: partial.text })
          break
        case 'tool-call':
          if (partial.toolCallId !== undefined) {
            blocks.push({
              type: 'tool-call',
              id: partial.toolCallId,
              name: partial.toolCallName ?? '',
              arguments: partial.toolCallArguments,
            })
          }
          break
        default:
          break
      }
    }
    return blocks
  }

  /** The reported token usage, when the provider sent it. */
  get usage(): TokenUsage | undefined {
    return this._usage
  }

  /** The terminal finish reason, when the provider sent it. */
  get finish(): FinishReason | undefined {
    return this._finish
  }
}
