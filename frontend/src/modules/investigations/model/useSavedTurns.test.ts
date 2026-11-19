import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { ApiClient } from '../../../infrastructure/api/api';
import { ApiError } from '../../../shared/contracts/errors';
import { useSavedTurns, type SavedContext } from './useSavedTurns';
import { useWorkspace } from './useWorkspace';
import type { SavedTurn } from '../../../shared/contracts/investigation-contracts';

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

it('keeps observing the same turn when its explicit Stop request fails', async () => {
  const api = new ApiClient();
  const running = snapshot({ state: 'running', revision: 0, finished_at: null });
  vi.spyOn(api, 'turn').mockResolvedValue(running);
  let observerSignal: AbortSignal | undefined;
  const observer = vi.spyOn(api, 'observeTurn').mockImplementation(async (_id, _receive, signal) => {
    observerSignal = signal;
    await new Promise<void>((resolve) => signal.addEventListener('abort', () => resolve(), { once: true }));
  });
  const cancel = vi.spyOn(api, 'cancelTurn').mockRejectedValue(new TypeError('Stop response unavailable'));
  const submissions = vi.spyOn(api, 'startTurn');
  const { result } = renderHook(() => useSavedTurns(api, 'local', undefined, context([running])));

  await waitFor(() => expect(observer).toHaveBeenCalledOnce());
  await act(async () => {
    await result.current.stop();
  });
  expect(cancel).toHaveBeenCalledOnce();
  expect(cancel.mock.calls[0]?.[0]).toBe(running.id);
  expect(observerSignal?.aborted).toBe(false);
  expect(result.current.running).toBe(true);
  expect(result.current.error).toBe('Could not stop the diagnosis. Check the saved turn.');
  expect(submissions).not.toHaveBeenCalled();
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
  let secondSignal: AbortSignal | undefined;
  vi.spyOn(api, 'observeTurn').mockImplementation(async (id, _receive, signal) => {
    if (id === second.id) secondSignal = signal;
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
  await waitFor(() => expect(secondSignal).toBeDefined());
  await act(async () => {
    finish({ ...first, state: 'stopped', revision: 1 });
    await stopping!;
  });
  expect(secondSignal?.aborted).toBe(false);
  expect(result.current.running).toBe(true);
  await act(async () => {
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

it('uses a late clarification as the latest target even when its question is shown above others', () => {
  const group = { kind: 'compose', name: 'commerce' } as const;
  const parent = snapshot({ state: 'awaiting_selection' });
  const container = snapshot({ target: { kind: 'container', id: 'a'.repeat(64), name: 'payments-api' } });
  const clarification = snapshot({ clarification_of: parent.id, target: group });
  const { result } = renderHook(() =>
    useSavedTurns(new ApiClient(), 'local', undefined, context([parent, container, clarification])),
  );
  expect(result.current.turns.at(-1)?.id).toBe(container.id);
  expect(result.current.lastTarget).toEqual(group);
});

it('keeps an unsupported saved answer visible without discarding supported history', () => {
  const api = new ApiClient();
  const supported = snapshot();
  const saved = context([supported]);
  saved.detail = {
    ...saved.detail!,
    turns: { items: [{ id: 'unsupported-answer', code: 'history_unsupported' }, supported], next_cursor: null },
  };
  const submissions = vi.spyOn(api, 'startTurn');
  const { result } = renderHook(() => useSavedTurns(api, 'local', undefined, saved));

  expect(result.current.turns).toHaveLength(2);
  expect(result.current.turns[0]).toMatchObject({
    id: 'unsupported-answer',
    state: 'failed',
    code: 'history_unsupported',
    error: 'This saved answer uses an unsupported schema.',
  });
  expect(result.current.turns[1]).toMatchObject({ id: supported.id, query: supported.query });
  expect(submissions).not.toHaveBeenCalled();
});

it('retains saved answers and the cursor when loading older history fails', async () => {
  const api = new ApiClient();
  const existing = snapshot();
  const saved = context([existing]);
  saved.detail = { ...saved.detail!, turns: { items: [existing], next_cursor: 'older-page' } };
  const older = vi.spyOn(api, 'olderTurns').mockRejectedValue(new TypeError('Read unavailable'));
  const submissions = vi.spyOn(api, 'startTurn');
  const { result } = renderHook(() => useSavedTurns(api, 'local', undefined, saved));

  await act(async () => {
    await result.current.older();
  });

  expect(older).toHaveBeenCalledOnce();
  expect(result.current.turns[0]).toMatchObject({ id: existing.id, query: existing.query });
  expect(result.current.nextCursor).toBe('older-page');
  expect(result.current.olderLoading).toBe(false);
  expect(result.current.error).toBe('Could not load older answers.');
  expect(submissions).not.toHaveBeenCalled();
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
    submission_id: expect.any(String) as unknown,
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

it('reports an unresolved lost acceptance without submitting again or observing another turn', async () => {
  vi.useFakeTimers();
  const api = new ApiClient();
  const saved = context([]);
  const submissions = vi.spyOn(api, 'startTurn').mockRejectedValue(new TypeError('Lost response'));
  const reads = vi.spyOn(api, 'investigation').mockResolvedValue(saved.detail!);
  const observations = vi.spyOn(api, 'observeTurn');
  const { result } = renderHook(() => useSavedTurns(api, 'local', undefined, saved));

  await act(async () => {
    await result.current.run('Original question');
    await vi.advanceTimersByTimeAsync(30_000);
  });

  expect(submissions).toHaveBeenCalledOnce();
  expect(reads).toHaveBeenCalledOnce();
  expect(observations).not.toHaveBeenCalled();
  expect(result.current.turns).toEqual([]);
  expect(result.current.errorSource).toBe('client');
  expect(result.current.error).toBe('Could not submit the question. Check saved history before trying again.');
  expect(saved.detail?.workspace.draft).toBe('My draft');
});

it('preserves the live workspace draft when recovery finds an unrelated submission', async () => {
  const api = new ApiClient();
  const initial = context([]).detail!;
  const unrelated = snapshot();
  const recovered = { ...initial, turns: { items: [unrelated], next_cursor: null }, turn_count: 1 };
  vi.spyOn(api, 'actorWorkspace').mockResolvedValue({
    revision: 0,
    last_investigation_id: initial.id,
    host: 'local',
    model: null,
  });
  const reads = vi.spyOn(api, 'investigation').mockResolvedValueOnce(initial).mockResolvedValue(recovered);
  const writes = vi.spyOn(api, 'saveWorkspace').mockImplementation(async (_id, revision, changes) => ({
    ...initial.workspace,
    ...changes,
    revision: revision + 1,
  }));
  const submissions = vi.spyOn(api, 'startTurn').mockRejectedValue(new TypeError('Lost response'));
  const observations = vi.spyOn(api, 'observeTurn');
  const { result } = renderHook(() => {
    const workspace = useWorkspace(api);
    const turns = useSavedTurns(api, 'local', undefined, {
      ...workspace,
      enabled: !workspace.loading,
      conflict: workspace.conflictWith,
      changed: () => {},
    });
    return { workspace, turns };
  });
  await waitFor(() => expect(result.current.workspace.ready).toBe(true));
  vi.useFakeTimers();
  act(() => result.current.workspace.setDraft('Live unsent draft'));
  await act(async () => {
    await result.current.turns.run('Original question');
    await vi.advanceTimersByTimeAsync(30_000);
  });
  expect(submissions).toHaveBeenCalledOnce();
  expect(submissions.mock.calls[0]?.[1].submission_id).not.toBe(unrelated.submission_id);
  expect(reads).toHaveBeenCalledTimes(2); // bootstrap and one recovery read
  expect(observations).not.toHaveBeenCalled();
  expect(writes).toHaveBeenCalledWith(initial.id, 4, { draft: 'Live unsent draft' });
  expect(result.current.workspace.draft).toBe('Live unsent draft');
  expect(result.current.turns.turns).toEqual([]);
  expect(result.current.turns.errorSource).toBe('client');
  expect(result.current.turns.error).toBe('Could not submit the question. Check saved history before trying again.');
});

it('waits for both visibility and connectivity before reading the existing running turn', async () => {
  const online = vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false);
  const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden');
  const api = new ApiClient();
  const running = snapshot({ state: 'running', revision: 0, finished_at: null });
  const reads = vi.spyOn(api, 'turn').mockResolvedValue({ ...running, state: 'completed', revision: 1 });
  const submissions = vi.spyOn(api, 'startTurn');
  renderHook(() => useSavedTurns(api, 'local', undefined, context([running])));

  await act(async () => {});
  expect(reads).not.toHaveBeenCalled();
  online.mockReturnValue(true);
  await act(async () => {
    window.dispatchEvent(new Event('online'));
  });
  expect(reads).not.toHaveBeenCalled();
  visibility.mockReturnValue('visible');
  await act(async () => {
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await waitFor(() => expect(reads).toHaveBeenCalledOnce());
  expect(reads.mock.calls[0]?.[0]).toBe(running.id);
  expect(submissions).not.toHaveBeenCalled();
});

it('detaches a hidden offline observer before it can read after reconnect', async () => {
  const online = vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false);
  const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden');
  const api = new ApiClient();
  const running = snapshot({ state: 'running', revision: 0, finished_at: null });
  const reads = vi.spyOn(api, 'turn');
  const submissions = vi.spyOn(api, 'startTurn');
  const { unmount } = renderHook(() => useSavedTurns(api, 'local', undefined, context([running])));

  await act(async () => {});
  unmount();
  online.mockReturnValue(true);
  visibility.mockReturnValue('visible');
  await act(async () => {
    window.dispatchEvent(new Event('online'));
    document.dispatchEvent(new Event('visibilitychange'));
  });
  expect(reads).not.toHaveBeenCalled();
  expect(submissions).not.toHaveBeenCalled();
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
