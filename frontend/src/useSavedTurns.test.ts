import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { ApiClient, ApiError } from './api';
import { useSavedTurns, type SavedContext } from './useSavedTurns';
import type { SavedTurn } from './investigation-contracts';

/** Supply a complete safe snapshot while varying only behavior relevant to the case. */
function snapshot(changes: Partial<SavedTurn> = {}): SavedTurn {
  return {
    schema_version: 1,
    id: crypto.randomUUID(),
    investigation_id: '11111111-1111-4111-8111-111111111111',
    actor: 'operator',
    host: 'local',
    submission_id: crypto.randomUUID(),
    request_id: 'originating-request',
    query: 'Original question',
    target: null,
    model: null,
    clarification_of: null,
    resolved_by_turn_id: null,
    state: 'completed',
    revision: 2,
    created_at: '2026-11-04T12:00:00Z',
    updated_at: '2026-11-04T12:00:00Z',
    finished_at: '2026-11-04T12:00:00Z',
    progress: [],
    progress_truncated: false,
    trace: [],
    answer: null,
    selection: null,
    error: null,
    ...changes,
  };
}

/** Bind a safe archive and revision controls without starting any background work. */
function context(items: SavedTurn[]): SavedContext {
  const row = items[0] ?? snapshot();
  return {
    detail: {
      id: row.investigation_id,
      host: row.host,
      title: row.query,
      created_at: row.created_at,
      updated_at: row.updated_at,
      active_turn_id: items.find((turn) => turn.state === 'running')?.id ?? null,
      turn_count: items.length,
      workspace: { revision: 4, draft: 'My draft', target: null, selected_container: null, view: 'diagnostics' },
      turns: { items, next_cursor: null },
    },
    flush: async () => true,
    revision: () => 4,
    refresh: async () => {},
    changed: () => {},
  };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

it('adopts a refreshed running turn once and stops that exact turn without submitting', async () => {
  const api = new ApiClient();
  const previous = snapshot();
  const running = snapshot({ state: 'running', revision: 0, finished_at: null });
  const reads: string[] = [];
  const observers: string[] = [];
  const cancellations: string[] = [];
  vi.spyOn(api, 'turn').mockImplementation(async (id) => {
    reads.push(id);
    return running;
  });
  vi.spyOn(api, 'observeTurn').mockImplementation(async (id, _receive, signal) => {
    observers.push(id);
    await new Promise<void>((resolve) => signal.addEventListener('abort', () => resolve(), { once: true }));
  });
  vi.spyOn(api, 'cancelTurn').mockImplementation(async (id) => {
    cancellations.push(id);
    return { ...running, state: 'stopped', revision: 1 };
  });
  const post = vi.spyOn(api, 'startTurn');
  const { result, rerender } = renderHook(({ saved }) => useSavedTurns(api, 'local', undefined, saved), {
    initialProps: { saved: context([previous]) },
  });
  await act(async () => {
    rerender({ saved: context([previous, running]) });
  });
  await waitFor(() => expect(result.current.running).toBe(true));
  await act(async () => {
    rerender({ saved: context([previous, running]) });
    await result.current.stop();
  });
  expect({ reads, observers, cancellations }).toEqual({
    reads: [running.id],
    observers: [running.id],
    cancellations: [running.id],
  });
  expect(result.current.running).toBe(false);
  expect(post).not.toHaveBeenCalled();
});

it('keeps one observer when local acceptance refreshes the active turn identity', async () => {
  const api = new ApiClient();
  const running = snapshot({ state: 'running', revision: 0, finished_at: null });
  const saved = context([]);
  const post = vi.spyOn(api, 'startTurn').mockResolvedValue({ snapshot: running, created: true });
  const reads = vi.spyOn(api, 'turn').mockResolvedValue(running);
  const observers = vi.spyOn(api, 'observeTurn').mockImplementation(async (_id, _receive, signal) => {
    await new Promise<void>((resolve) => signal.addEventListener('abort', () => resolve(), { once: true }));
  });
  const { result, rerender } = renderHook(({ current }) => useSavedTurns(api, 'local', undefined, current), {
    initialProps: { current: saved },
  });
  saved.refresh = async () => {
    rerender({ current: { ...saved, detail: context([running]).detail } });
  };
  await act(async () => {
    await result.current.run('Original question');
  });
  expect(post).toHaveBeenCalledTimes(1);
  expect(reads).toHaveBeenCalledTimes(1);
  expect(observers).toHaveBeenCalledTimes(1);
  expect(result.current.running).toBe(true);
});

it('keeps cancellation ownership on a newer refreshed turn when an older Stop response arrives late', async () => {
  const api = new ApiClient();
  const first = snapshot({ state: 'running', revision: 0, finished_at: null });
  const second = snapshot({ state: 'running', revision: 0, finished_at: null });
  const reads: string[] = [];
  vi.spyOn(api, 'turn').mockImplementation(async (id) => {
    reads.push(id);
    return id === first.id ? first : second;
  });
  vi.spyOn(api, 'observeTurn').mockImplementation(async (_id, _receive, signal) => {
    await new Promise<void>((resolve) => signal.addEventListener('abort', () => resolve(), { once: true }));
  });
  let finish: (row: SavedTurn) => void = () => {};
  const cancellations: string[] = [];
  vi.spyOn(api, 'cancelTurn').mockImplementation(async (id) => {
    cancellations.push(id);
    if (id === first.id)
      return new Promise((resolve) => {
        finish = resolve;
      });
    return { ...second, state: 'stopped', revision: 1 };
  });
  const { result, rerender } = renderHook(({ saved }) => useSavedTurns(api, 'local', undefined, saved), {
    initialProps: { saved: context([first]) },
  });
  await waitFor(() => expect(reads).toEqual([first.id]));
  let stopping: Promise<void>;
  act(() => {
    stopping = result.current.stop();
  });
  await act(async () => {
    rerender({ saved: context([{ ...first, state: 'stopped', revision: 1 }, second]) });
  });
  await waitFor(() => expect(reads).toEqual([first.id, second.id]));
  await act(async () => {
    finish({ ...first, state: 'stopped', revision: 1 });
    await stopping!;
    await result.current.stop();
  });
  expect(cancellations).toEqual([first.id, second.id]);
});

it('preserves server-authored admission errors even when their text matches local copy', async () => {
  const api = new ApiClient();
  vi.spyOn(api, 'startTurn').mockRejectedValue(
    new ApiError('Observation disconnected. Reconnecting to the saved turn.', 'admission_failed'),
  );
  const saved = context([]);
  const { result } = renderHook(() => useSavedTurns(api, 'local', undefined, saved));
  await act(async () => {
    await result.current.run('Original question');
  });
  expect(result.current.errorSource).toBe('server');
});

it('groups nested clarification attempts under one original question', () => {
  const parent = snapshot({ state: 'awaiting_selection' });
  const child = snapshot({ clarification_of: parent.id, state: 'awaiting_selection' });
  const final = snapshot({ clarification_of: child.id });
  const { result } = renderHook(() =>
    useSavedTurns(new ApiClient(), 'local', undefined, context([parent, child, final])),
  );
  expect(result.current.turns).toHaveLength(1);
  expect(result.current.turns[0]?.attempts).toHaveLength(3);
});

it('posts clarification without replacement text and retains parent compare-and-swap', async () => {
  const api = new ApiClient();
  const target = { kind: 'compose' as const, name: 'shop' };
  const parent = snapshot({ state: 'awaiting_selection', selection: { candidates: [target] } });
  const child = snapshot({ clarification_of: parent.id, target });
  let input: unknown;
  vi.spyOn(api, 'startTurn').mockImplementation(async (_id, body) => {
    input = body;
    return { snapshot: child, created: true };
  });
  const { result } = renderHook(() => useSavedTurns(api, 'local', undefined, context([parent])));
  await act(async () => {
    await result.current.chooseTarget(parent.id, target);
  });
  expect(input).toEqual({
    kind: 'clarification',
    clarification_of: parent.id,
    expected_parent_revision: parent.revision,
    expected_revision: 4,
    target,
    model: null,
    submission_id: expect.any(String),
  });
  expect(result.current.turns).toHaveLength(1);
});

it('recovers a lost acceptance response through an owned read without posting again', async () => {
  const api = new ApiClient();
  let accepted = snapshot();
  let submissions = 0;
  vi.spyOn(api, 'startTurn').mockImplementation(async (_id, body) => {
    submissions++;
    accepted = { ...accepted, submission_id: body.submission_id };
    throw new TypeError('Lost response');
  });
  vi.spyOn(api, 'investigation').mockImplementation(async () => context([accepted]).detail!);
  const { result } = renderHook(() => useSavedTurns(api, 'local', undefined, context([])));
  await act(async () => {
    await result.current.run('Original question');
  });
  expect(submissions).toBe(1);
  expect(result.current.turns[0]?.serverTurnId).toBe(accepted.id);
});

it('stops observer retries on authentication rejection and never resubmits', async () => {
  const api = new ApiClient();
  const row = snapshot({ state: 'running' });
  let reads = 0;
  vi.spyOn(api, 'turn').mockImplementation(async () => {
    reads++;
    throw new ApiError('Sign in', 'unauthorized', undefined, 'server', 401);
  });
  const post = vi.spyOn(api, 'startTurn');
  const { result } = renderHook(() => useSavedTurns(api, 'local', undefined, context([row])));
  await waitFor(() => expect(result.current.error).toContain('Sign in again'));
  vi.useFakeTimers();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(30_000);
  });
  expect(reads).toBe(1);
  expect(post).not.toHaveBeenCalled();
});
