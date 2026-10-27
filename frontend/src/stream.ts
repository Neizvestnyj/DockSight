import { eventSchema, type TurnEvent } from './contracts';

/** Decode complete SSE frames without treating transport success as turn success. */
export async function consumeEvents(response: Response, receive: (event: TurnEvent) => void): Promise<void> {
  if (!response.body) throw new Error('The diagnostic stream has no body.');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let terminal = false;
  try {
    while (!terminal) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      // Normalize only complete CRLF pairs; a CR may arrive in the previous chunk.
      buffer = buffer.replace(/\r\n/g, '\n');
      let boundary: number;
      while ((boundary = buffer.indexOf('\n\n')) !== -1) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const data = frame
          .split('\n')
          .filter((line) => line.startsWith('data:'))
          .map((line) => line.slice(5).replace(/^ /, ''))
          .join('\n');
        if (!data) continue;
        const event = eventSchema.parse(JSON.parse(data));
        receive(event);
        terminal = event.type === 'turn.completed' || event.type === 'turn.failed';
        if (terminal) break;
      }
      if (buffer.length > 2_000_000) throw new Error('Diagnostic event exceeded the supported size.');
      if (done) break;
    }
    if (!terminal) throw new Error('Connection ended before the diagnostic turn completed. Retry manually.');
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}
