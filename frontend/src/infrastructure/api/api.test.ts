import { describe, expect, it, vi } from 'vitest';
import { ApiClient } from './api';
import { consumeEvents } from './stream';
import { demoContainer, demoSystemStatus } from '../demo/demo';

it('keeps a chat query in the request body and scopes container search to the chosen host and group', async () => {
  const client = new ApiClient('/api/v1', 'token', async (url, init) => {
    if (url === '/api/v1/investigations/search') {
      expect(init?.method).toBe('POST');
      expect(init?.body).toBe(JSON.stringify({ q: 'connection refused', before: 'older' }));
    } else {
      expect(url).toBe('/api/v1/hosts/host%20id/container-search?q=web+api&group_kind=compose&group_name=shop');
    }
    return Response.json({ items: [], next_cursor: null });
  });
  const signal = new AbortController().signal;
  expect(await client.searchInvestigations('connection refused', signal, 'older')).toEqual({
    items: [],
    next_cursor: null,
  });
  expect(await client.searchContainers('host id', 'web api', signal, { kind: 'compose', name: 'shop' })).toEqual({
    items: [],
    next_cursor: null,
  });
});

describe('direct container reads', () => {
  it('exchanges a first-party bearer once and keeps subsequent credentials in the cookie contract', async () => {
    const calls: RequestInit[] = [];
    const client = new ApiClient('/api/v1', '', async (_url, init) => {
      calls.push(init!);
      return Response.json({ actor: 'operator', expires_at: '2026-11-05T12:00:00Z', csrf_token: 'c'.repeat(43) });
    });
    await client.login('one-time-secret');
    await client.session();
    await client.logout();
    expect(new Headers(calls[0]!.headers).get('Authorization')).toBe('Bearer one-time-secret');
    expect(new Headers(calls[1]!.headers).has('Authorization')).toBe(false);
    expect(new Headers(calls[2]!.headers).get('X-CSRF-Token')).toBe('c'.repeat(43));
    expect(calls.every((call) => call.credentials === 'same-origin')).toBe(true);
  });

  it('omits browser credentials in transient bearer mode', async () => {
    let credentials: RequestCredentials | undefined;
    const client = new ApiClient('https://remote.example/api/v1', 'transient', async (_url, init) => {
      credentials = init?.credentials;
      return Response.json([]);
    });
    await client.hosts(new AbortController().signal);
    expect(credentials).toBe('omit');
  });
  it('authenticates, scopes, and validates state, bounded logs, and current metrics', async () => {
    const snapshot = demoContainer(0, 'test host', '2026-10-27T12:00:00Z');
    const fetcher = vi.fn(async (url: string | URL | Request) => {
      // The fixture preserves the fetch input's original string coercion.
      // eslint-disable-next-line @typescript-eslint/no-base-to-string
      const path = String(url);
      return Response.json(
        path.endsWith('/stats')
          ? snapshot.metrics
          : path.includes('/logs?')
            ? { entries: [{ message: 'original log', timestamp: null }], truncated: true }
            : snapshot,
      );
    });
    const client = new ApiClient('/api/v1', 'private-token', fetcher);
    const signal = new AbortController().signal;
    expect(await client.container(snapshot.host, snapshot.id, signal)).toEqual(snapshot);
    expect(await client.logs(snapshot.host, snapshot.id, signal)).toEqual({
      entries: [{ message: 'original log', timestamp: null }],
      truncated: true,
    });
    expect(await client.stats(snapshot.host, snapshot.id, signal)).toEqual(snapshot.metrics);
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual([
      `/api/v1/hosts/test%20host/containers/${snapshot.id}`,
      `/api/v1/hosts/test%20host/containers/${snapshot.id}/logs?lines=200`,
      `/api/v1/hosts/test%20host/containers/${snapshot.id}/stats`,
    ]);
    for (const call of fetcher.mock.calls) {
      const init = (call as unknown as [string, RequestInit])[1];
      expect(new Headers(init.headers).get('Authorization')).toBe('Bearer private-token');
      expect(init.signal).toBeDefined();
    }
  });

  it('rejects invalid observations and a snapshot for another resource', async () => {
    const snapshot = demoContainer(1, 'local', '2026-10-27T12:00:00Z');
    const client = new ApiClient('', 'token', async () => Response.json(snapshot));
    const signal = new AbortController().signal;
    await expect(client.container('local', '1'.repeat(64), signal)).rejects.toThrow();
    await expect(client.logs('local', snapshot.id, signal)).rejects.toThrow();
    await expect(client.stats('local', snapshot.id, signal)).rejects.toThrow();
  });
});

it('rejects valid system status data for a different host or selected model', async () => {
  const local = demoSystemStatus('local');
  const selected = { provider: local.provider, model: local.model };
  const fetcher = vi
    .fn<typeof fetch>()
    .mockResolvedValueOnce(Response.json({ ...local, host: 'other' }))
    .mockResolvedValueOnce(Response.json({ ...local, model: 'different-model' }))
    .mockResolvedValueOnce(Response.json(local));
  const client = new ApiClient('/api/v1', 'token', fetcher);
  const signal = new AbortController().signal;
  await expect(client.systemStatus('local', signal, selected)).rejects.toMatchObject({ code: 'status_unsupported' });
  await expect(client.systemStatus('local', signal, selected)).rejects.toMatchObject({ code: 'status_unsupported' });
  await expect(client.systemStatus('local', signal, selected)).resolves.toEqual(local);
  expect(fetcher.mock.calls.map(([url]) => url)).toEqual(
    Array<string>(3).fill(`/api/v1/system/status?${new URLSearchParams({ host: 'local', ...selected })}`),
  );
});

it('rejects another grouping kind before presenting an exact diagnosis scope', async () => {
  const fetcher = vi.fn<typeof fetch>(async () =>
    Response.json([{ name: 'shop', kind: 'swarm', total: 0, running: 0, container_ids: [], members: [] }]),
  );
  const client = new ApiClient('/api/v1', 'token', fetcher);
  await expect(client.stacks('local', 'compose', new AbortController().signal)).rejects.toThrow(
    'Group response is outside the selected scope.',
  );
  expect(fetcher).toHaveBeenCalledExactlyOnceWith('/api/v1/hosts/local/stacks?kind=compose', expect.any(Object));
});

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
    expect(JSON.parse(String(init.body as string))).toEqual({ host: 'local', query: 'Why?' });
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

  it('uses the supplied key and confirmed=true even when HTTP succeeds with failed state', async () => {
    let init: RequestInit | undefined;
    const client = new ApiClient('', 'token', async (_url, options) => {
      init = options;
      return Response.json({ ...action, state: 'failed' });
    });
    expect((await client.execute(action.id, 'original-key')).state).toBe('failed');
    expect(new Headers(init?.headers).get('Idempotency-Key')).toBe('original-key');
    expect(JSON.parse(String(init?.body as string))).toEqual({ confirmed: true });
  });
});

it('preserves the server conflict revision and request identity for draft recovery', async () => {
  const current = {
    revision: 9,
    draft: 'Acknowledged draft',
    target: null,
    selected_container: null,
    view: 'diagnostics',
  };
  const fetcher = vi.fn<typeof fetch>(async () =>
    Response.json(
      { code: 'workspace_conflict', message: 'Revision changed', request_id: 'conflict-request', current },
      { status: 409 },
    ),
  );
  const client = new ApiClient('/api/v1', 'token', fetcher);
  const id = crypto.randomUUID();
  await expect(client.saveWorkspace(id, 8, { draft: 'Local draft' })).rejects.toMatchObject({
    code: 'workspace_conflict',
    requestId: 'conflict-request',
    httpStatus: 409,
    current,
  });
  expect(fetcher).toHaveBeenCalledExactlyOnceWith(
    `/api/v1/investigations/${id}/workspace`,
    expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ expected_revision: 8, draft: 'Local draft' }) }),
  );
});
