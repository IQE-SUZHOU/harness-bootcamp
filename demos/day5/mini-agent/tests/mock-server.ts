/**
 * A local mock of the DeepSeek Messages API, for exercising the CLI without
 * an API key.
 *
 * Usage: node --experimental-strip-types tests/mock-server.ts [port]
 */

import { createServer } from 'node:http'
import type { AddressInfo } from 'node:net'

/** One SSE frame. */
interface Frame {
  event: string
  data: string
}

/** Build the frames of a plain text answer. */
function textFrames(text: string): Frame[] {
  return [
    { event: 'message_start', data: JSON.stringify({ type: 'message_start', message: { usage: { input_tokens: 11, output_tokens: 0 } } }) },
    { event: 'content_block_start', data: JSON.stringify({ type: 'content_block_start', index: 0, content_block: { type: 'text', text: '' } }) },
    { event: 'content_block_delta', data: JSON.stringify({ type: 'content_block_delta', index: 0, delta: { type: 'text_delta', text } }) },
    { event: 'content_block_stop', data: JSON.stringify({ type: 'content_block_stop', index: 0 }) },
    { event: 'message_delta', data: JSON.stringify({ type: 'message_delta', delta: { stop_reason: 'end_turn' }, usage: { output_tokens: 7 } }) },
    { event: 'message_stop', data: JSON.stringify({ type: 'message_stop' }) },
  ]
}

/** Build the frames of a tool call request. */
function toolFrames(id: string, name: string, args: unknown): Frame[] {
  return [
    { event: 'message_start', data: JSON.stringify({ type: 'message_start', message: { usage: { input_tokens: 11, output_tokens: 0 } } }) },
    { event: 'content_block_start', data: JSON.stringify({ type: 'content_block_start', index: 0, content_block: { type: 'tool_use', id, name, input: {} } }) },
    { event: 'content_block_delta', data: JSON.stringify({ type: 'content_block_delta', index: 0, delta: { type: 'input_json_delta', partial_json: JSON.stringify(args) } }) },
    { event: 'content_block_stop', data: JSON.stringify({ type: 'content_block_stop', index: 0 }) },
    { event: 'message_delta', data: JSON.stringify({ type: 'message_delta', delta: { stop_reason: 'tool_use' }, usage: { output_tokens: 9 } }) },
    { event: 'message_stop', data: JSON.stringify({ type: 'message_stop' }) },
  ]
}

let requestCount = 0
const server = createServer((req, res) => {
  const chunks: Buffer[] = []
  req.on('data', chunk => { chunks.push(chunk as Buffer) })
  req.on('end', () => {
    const body = JSON.parse(Buffer.concat(chunks).toString('utf8')) as { messages: unknown[] }
    requestCount += 1
    console.error(`[mock] request ${requestCount}: ${body.messages.length} messages`)
    let frames: Frame[]
    if (requestCount === 1) {
      frames = toolFrames('toolu_1', 'bash', { command: 'echo "hello from the tool"' })
    } else {
      frames = textFrames('The tool printed: hello from the tool')
    }
    res.writeHead(200, { 'content-type': 'text/event-stream' })
    for (const frame of frames) {
      res.write(`event: ${frame.event}\ndata: ${frame.data}\n\n`)
    }
    res.end()
  })
})

server.listen(0, '127.0.0.1', () => {
  const address = server.address() as AddressInfo
  console.log(`http://127.0.0.1:${address.port}`)
})
