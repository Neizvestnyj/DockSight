import { describe, expect, it, vi } from 'vitest';
import { ApiClient, executeOnce } from './api';
import { consumeEvents } from './stream';

/** Encode arbitrary byte splits as a streamed HTTP response. */
function streamResponse(text: string, size = 7): Response {
  const bytes = new TextEncoder().encode(text);
  return new Response(
    new ReadableStream({
      start(controller) {
        for (let i = 0; i < bytes.length; i += size) controller.enqueue(bytes.slice(i, i + size));
        controller.close();
      },
    }),
    { headers: { 'Content-Type': 'text/event-stream' } },
  );
}

const envelope = { schema_version: 1, request_id: 'req-1', turn_id: 'turn-1' };

describe('diagnostic stream', () => {
  it('calls fetch without binding its receiver to the API client', async () => {
    const fetcher: typeof fetch = async function (this: unknown) {
      if (this !== undefined) throw new TypeError('Illegal invocation');
      return Response.json([{ id: 'local', name: 'Local Docker' }]);
    };
    const client = new ApiClient('', 'token', fetcher);
    await expect(client.hosts(new AbortController().signal)).resolves.toEqual([{ id: 'local', name: 'Local Docker' }]);
  });
  it('decodes split UTF-8, CRLF, multiline data, and heartbeats', async () => {
    const events: unknown[] = [];
    const body =
      ': heartbeat\r\n\r\nevent: turn.failed\r\ndata: {"type":"turn.failed",\r\ndata: "schema_version":1,"request_id":"r","turn_id":null,"code":"error","message":"café unavailable"}\r\n\r\n';
    await consumeEvents(streamResponse(body, 1), (event) => events.push(event));
    expect(events).toEqual([expect.objectContaining({ type: 'turn.failed', message: 'café unavailable' })]);
  });

  it('delivers HTTP-200 turn.failed as a failure event', async () => {
    const events: unknown[] = [];
    const client = new ApiClient('', 'private-token', async () =>
      streamResponse(
        `data: ${JSON.stringify({ ...envelope, type: 'turn.failed', code: 'model_timeout', message: 'Model timed out' })}\n\n`,
      ),
    );
    await client.diagnose(
      { host: 'local', query: 'Why?' },
      (event) => events.push(event),
      new AbortController().signal,
    );
    expect(events).toContainEqual(expect.objectContaining({ type: 'turn.failed' }));
  });

  it('rejects premature EOF without a terminal event', async () => {
    await expect(
      consumeEvents(
        streamResponse(
          `data: ${JSON.stringify({ ...envelope, type: 'turn.started', session_id: '4a59a145-0037-4934-92e0-f422105583b9' })}\n\n`,
        ),
        () => {},
      ),
    ).rejects.toThrow(/before.*completed/i);
  });

  it('rejects unsupported event versions', async () => {
    await expect(
      consumeEvents(streamResponse('data: {"type":"turn.completed","schema_version":2}\n\n'), () => {}),
    ).rejects.toThrow();
  });

  it('sends bearer auth and scopes the POST body to its host and session', async () => {
    const fetcher = vi.fn(async () =>
      streamResponse(`data: ${JSON.stringify({ ...envelope, type: 'turn.completed' })}\n\n`),
    );
    const client = new ApiClient('/api/v1', 'private-token', fetcher);
    await client.diagnose({ host: 'local', query: 'Why?' }, () => {}, new AbortController().signal);
    const [url, init] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('/api/v1/chat/turns');
    expect(new Headers(init.headers).get('Authorization')).toBe('Bearer private-token');
    expect(JSON.parse(String(init.body))).toEqual({ host: 'local', query: 'Why?' });
  });
});

describe('action recovery', () => {
  const action = {
    id: 'action-1',
    state: 'indeterminate',
    host: 'local',
    container_id: 'a'.repeat(64),
    operation: 'restart',
    expires_at: '2026-10-27T12:00:00Z',
    confirmation_required: true,
    message: 'Unknown Docker result',
  } as const;

  it('reads an existing action after lost response without resubmitting a mutation', async () => {
    const api = {
      execute: vi.fn().mockRejectedValue(new TypeError('Network lost')),
      action: vi.fn().mockResolvedValue(action),
    };
    const result = await executeOnce(api, action.id, 'original-key');
    expect(result.state).toBe('indeterminate');
    expect(api.execute).toHaveBeenCalledTimes(1);
    expect(api.execute).toHaveBeenCalledWith(action.id, 'original-key');
    expect(api.action).toHaveBeenCalledWith(action.id);
  });

  it('uses the supplied key and confirmed=true even when HTTP succeeds with failed state', async () => {
    let init: RequestInit | undefined;
    const client = new ApiClient('', 'token', async (_url, options) => {
      init = options;
      return Response.json({ ...action, state: 'failed' });
    });
    expect((await client.execute(action.id, 'original-key')).state).toBe('failed');
    expect(new Headers(init?.headers).get('Idempotency-Key')).toBe('original-key');
    expect(JSON.parse(String(init?.body))).toEqual({ confirmed: true });
  });
});
