import '@testing-library/jest-dom/vitest';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';
import { demoAnswer, demoContainer, demoSystemStatus } from './demo';

beforeEach(() => {
  vi.useFakeTimers();
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
  vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(true);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

/** Serve changing Docker observations at the HTTP boundary, keeping transport validation real. */
function installApi() {
  const container = demoContainer(0, 'test-host', '2026-10-28T07:00:00Z');
  const api = {
    rows: [container],
    container,
    failed: false,
    missing: false,
    inspectFailed: false,
    pendingInspect: undefined as Promise<Response> | undefined,
    reads: [] as string[],
  };
  vi.stubGlobal('fetch', async (input: string) => {
    const url = new URL(input, 'http://localhost');
    const path = url.pathname;
    api.reads.push(path);
    if (path.endsWith('/system/status')) return Response.json(demoSystemStatus(url.searchParams.get('host')));
    if (path.endsWith('/hosts')) return Response.json([{ id: 'test-host', name: 'Test host' }]);
    if (path.endsWith('/containers'))
      return api.failed
        ? Response.json({ code: 'runtime_unavailable', message: 'Docker unavailable' }, { status: 503 })
        : Response.json(api.rows);
    if (path.endsWith('/logs')) return Response.json({ entries: [], truncated: false });
    if (path.endsWith('/stats'))
      return Response.json({ cpu_percent: 1, memory_usage_bytes: 100, memory_limit_bytes: 200 });
    if (path.endsWith('/chat/turns')) {
      const envelope = { schema_version: 1, request_id: 'r', turn_id: 't' };
      const answer = { ...envelope, type: 'answer.ready', answer: demoAnswer('crash_loop', 'test-host') };
      const completed = { ...envelope, type: 'turn.completed' };
      return new Response(`data: ${JSON.stringify(answer)}\n\ndata: ${JSON.stringify(completed)}\n\n`, {
        headers: { 'Content-Type': 'text/event-stream' },
      });
    }
    if (api.pendingInspect) return api.pendingInspect;
    if (api.inspectFailed)
      return Response.json({ code: 'runtime_unavailable', message: 'Docker unavailable' }, { status: 503 });
    return api.missing
      ? Response.json({ code: 'container_not_found', message: 'Container not found' }, { status: 404 })
      : Response.json(api.container);
  });
  return api;
}

/** Connect through the product flow without persisting credentials. */
async function connect() {
  render(<App />);
  await act(async () => {});
  fireEvent.click(screen.getByRole('button', { name: 'Connect API' }));
  fireEvent.change(screen.getByLabelText('Bearer token'), { target: { value: 'test-token' } });
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Connect' })));
}

/** Settle the next refresh while publishing its resulting React state. */
async function advance(milliseconds = 10_000) {
  await act(async () => vi.advanceTimersByTimeAsync(milliseconds));
}

describe('automatic inventory refresh', () => {
  it('discovers new containers and changed states while preserving focus, drafts, and diagnostic evidence', async () => {
    const api = installApi();
    await connect();
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Explain this container' } });
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Investigate' })));
    const card = screen.getByRole('region', { name: 'Container status' });
    const observed = card.querySelector('time')!.dateTime;
    const action = screen.getByRole('button', { name: 'Review stop' });
    const draft = screen.getByRole('textbox');
    fireEvent.change(draft, { target: { value: 'Retain this follow-up' } });
    draft.focus();
    api.rows = [
      { ...api.container, state: 'exited' },
      { ...demoContainer(1, 'test-host', '2026-10-28T07:00:10Z'), name: 'new-worker' },
    ];
    await advance();
    expect(screen.getByTitle('payments-api')).toHaveTextContent('exited');
    expect(screen.getByTitle('new-worker')).toBeInTheDocument();
    expect(draft).toHaveValue('Retain this follow-up');
    expect(draft).toHaveFocus();
    expect(card.querySelector('time')!.dateTime).toBe(observed);
    expect(screen.getByRole('button', { name: 'Review stop' })).toBe(action);
    api.rows = [];
    await advance();
    expect(screen.queryByTitle('new-worker')).not.toBeInTheDocument();
    expect(screen.getByText('No containers on this host.')).toBeInTheDocument();
    expect(api.reads.filter((path) => path.endsWith('/chat/turns'))).toHaveLength(1);
    expect(api.reads.some((path) => path.includes('/actions'))).toBe(false);
  });

  it('retains the last list and receipt time after failure and recovers with backoff', async () => {
    const api = installApi();
    await connect();
    const feedback = document.querySelector('.inventory-feedback')!;
    const received = feedback.textContent;
    api.failed = true;
    await advance();
    expect(feedback).toHaveTextContent('Showing the last received list.');
    expect(screen.getByTitle('payments-api')).toBeInTheDocument();
    const reads = api.reads.length;
    api.failed = false;
    api.rows = [];
    await advance(19_999);
    expect(api.reads).toHaveLength(reads);
    await advance(1);
    expect(screen.getByText('No containers on this host.')).toBeInTheDocument();
    expect(feedback).not.toHaveTextContent('Refresh failed');
    expect(feedback.textContent).not.toBe(received);
  });

  it('refreshes the exact selected container and reports deletion without following a same-name replacement', async () => {
    const api = installApi();
    await connect();
    await act(async () => fireEvent.click(screen.getByTitle('payments-api')));
    const facts = screen.getByRole('region', { name: 'Container facts' });
    const panel = within(facts).getByRole('region', { name: 'Container status' });
    const logsTime = within(facts).getByRole('region', { name: 'Container logs' }).querySelector('time')!.dateTime;
    api.container = { ...api.container, state: 'exited', observed_at: '2026-10-28T07:00:10Z' };
    await advance();
    expect(panel).toHaveTextContent('exited');
    expect(within(facts).getByRole('region', { name: 'Container logs' }).querySelector('time')!.dateTime).toBe(
      logsTime,
    );
    api.rows = [{ ...api.container, id: 'f'.repeat(64), state: 'running' }];
    api.missing = true;
    await advance();
    expect(facts).toHaveTextContent('This container no longer exists on the selected host.');
    expect(facts).toHaveTextContent('1'.repeat(64));
    expect(facts).not.toHaveTextContent('f'.repeat(64));
    expect(within(facts).getByRole('button', { name: 'Diagnose' })).toBeDisabled();
    const inspectPath = `/api/v1/hosts/test-host/containers/${'1'.repeat(64)}`;
    const inspections = api.reads.filter((path) => path === inspectPath).length;
    await advance(60_000);
    expect(api.reads.filter((path) => path === inspectPath)).toHaveLength(inspections);
    expect(api.reads.filter((path) => path.endsWith('/logs'))).toHaveLength(1);
    expect(api.reads.filter((path) => path.endsWith('/stats'))).toHaveLength(1);
    expect(api.reads.some((path) => path.endsWith('/chat/turns'))).toBe(false);
    api.inspectFailed = true;
    await act(async () => fireEvent.click(within(facts).getByRole('button', { name: 'Refresh data' })));
    expect(facts).toHaveTextContent('This container no longer exists on the selected host.');
    const afterRetry = api.reads.filter((path) => path === inspectPath).length;
    await advance(60_000);
    expect(api.reads.filter((path) => path === inspectPath)).toHaveLength(afterRetry);
    api.inspectFailed = false;
    api.missing = false;
    await act(async () => fireEvent.click(within(facts).getByRole('button', { name: 'Refresh data' })));
    expect(facts).not.toHaveTextContent('This container no longer exists on the selected host.');
    expect(within(facts).getByRole('button', { name: 'Diagnose' })).toBeEnabled();
  });

  it('honors a manual logs and metrics refresh queued behind a slow automatic inspect', async () => {
    const api = installApi();
    await connect();
    await act(async () => fireEvent.click(screen.getByTitle('payments-api')));
    let finish: (response: Response) => void = () => {};
    api.pendingInspect = new Promise<Response>((resolve) => {
      finish = resolve;
    });
    await advance();
    const facts = screen.getByRole('region', { name: 'Container facts' });
    fireEvent.click(within(facts).getByRole('button', { name: 'Refresh data' }));
    expect(api.reads.filter((path) => path.endsWith('/logs'))).toHaveLength(1);
    api.pendingInspect = undefined;
    await act(async () => finish(Response.json(api.container)));
    expect(api.reads.filter((path) => path.endsWith('/logs'))).toHaveLength(2);
    expect(api.reads.filter((path) => path.endsWith('/stats'))).toHaveLength(2);
  });
});
