import { eventSchema, type TurnEvent } from './contracts';
import { z } from 'zod';
import { savedTurnSchema, type SavedTurn } from './investigation-contracts';

/** Read full committed snapshots, accepting revision coalescing and bounded frames. */
export async function consumeSnapshots(response: Response, receive: (snapshot: SavedTurn) => void): Promise<void> {
  if (!response.body) throw new Error('The diagnostic stream has no body.');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let revision = -1;
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer = (buffer + decoder.decode(value, { stream: !done })).replace(/\r\n/g, '\n');
      let boundary: number;
      while ((boundary = buffer.indexOf('\n\n')) !== -1) {
        if (boundary > 2 * 1024 * 1024) throw new Error('Diagnostic event exceeded the supported size.');
        const lines = buffer.slice(0, boundary).split('\n');
        buffer = buffer.slice(boundary + 2);
        const data = lines
          .filter((line) => line.startsWith('data:'))
          .map((line) => line.slice(5).trimStart())
          .join('\n');
        if (!data) continue;
        if (lines.includes('event: error')) {
          const failure = z
            .strictObject({ schema_version: z.literal(1), code: z.string().max(64), message: z.string().max(512) })
            .parse(JSON.parse(data));
          throw new Error(failure.message);
        }
        if (!lines.includes('event: turn.snapshot')) throw new Error('Unsupported observation event.');
        const snapshot = savedTurnSchema.parse(JSON.parse(data));
        const eventId = lines
          .find((line) => line.startsWith('id:'))
          ?.slice(3)
          .trim();
        if (eventId !== String(snapshot.revision)) throw new Error('Unsupported observation revision.');
        if (snapshot.revision > revision) {
          revision = snapshot.revision;
          receive(snapshot);
        }
        if (snapshot.state !== 'running') return;
      }
      if (buffer.length > 2 * 1024 * 1024) throw new Error('Diagnostic event exceeded the supported size.');
      if (done) throw new Error('Observation disconnected. Reconnecting to the saved turn.');
    }
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}

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
