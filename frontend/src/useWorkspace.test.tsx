import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiClient, ApiError } from './api';
import { useWorkspace } from './useWorkspace';

const id = '11111111-1111-4111-8111-111111111111';
const empty = { revision: 0, draft: '', target: null, selected_container: null, view: 'diagnostics' as const };
const detail = {
  id,
  host: 'local',
  title: 'Saved question',
  created_at: '2026-11-04T12:00:00Z',
  updated_at: '2026-11-04T12:00:00Z',
  active_turn_id: null,
  turn_count: 0,
  workspace: empty,
  turns: { items: [], next_cursor: null },
};
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe('revisioned workspace', () => {
  it('debounces drafts by 300 milliseconds and serializes a second edit behind acknowledgement', async () => {
    const api = new ApiClient();
    vi.spyOn(api, 'actorWorkspace').mockResolvedValue({
      revision: 0,
      last_investigation_id: id,
      host: 'local',
      model: null,
    });
    vi.spyOn(api, 'investigation').mockResolvedValue(detail);
    let finish: (value: typeof empty) => void = () => {};
    const writes: string[] = [];
    vi.spyOn(api, 'saveWorkspace').mockImplementation(async (_id, revision, patch) => {
      writes.push(`${revision}:${patch.draft}`);
      if (writes.length === 1)
        return new Promise((resolve) => {
          finish = resolve;
        });
      return { ...empty, revision: revision + 1, draft: patch.draft ?? '' };
    });
    const { result } = renderHook(() => useWorkspace(api));
    await waitFor(() => expect(result.current.ready).toBe(true));
    vi.useFakeTimers();
    act(() => result.current.setDraft('First edit'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(299);
    });
    expect(writes).toEqual([]);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    act(() => result.current.setDraft('Second edit'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(writes).toEqual(['0:First edit']);
    await act(async () => {
      finish({ ...empty, revision: 1, draft: 'First edit' });
    });
    expect(writes).toEqual(['0:First edit', '1:Second edit']);
    expect(result.current.draft).toBe('Second edit');
    expect(result.current.saveState).toBe('saved');
  });
  it('restores acknowledged drafts, serializes edits, and preserves dirty text on conflict', async () => {
    const api = new ApiClient();
    vi.spyOn(api, 'actorWorkspace').mockResolvedValue({
      revision: 0,
      last_investigation_id: id,
      host: 'local',
      model: null,
    });
    vi.spyOn(api, 'investigation').mockResolvedValue(detail);
    const writes: string[] = [];
    vi.spyOn(api, 'saveWorkspace').mockImplementation(async (_id, revision, patch) => {
      writes.push(`${revision}:${patch.draft}`);
      throw new ApiError('Changed elsewhere', 'workspace_conflict', undefined, 'server', 409, {
        ...empty,
        revision: 1,
        draft: 'Other tab',
      });
    });
    const { result } = renderHook(() => useWorkspace(api));
    await waitFor(() => expect(result.current.ready).toBe(true));
    act(() => result.current.setDraft('My unsent text'));
    await act(async () => {
      await result.current.flush();
    });
    expect(result.current.draft).toBe('My unsent text');
    expect(result.current.saveState).toBe('conflict');
    expect(writes).toEqual(['0:My unsent text']);
    act(() => result.current.reloadConflict());
    expect(result.current.draft).toBe('Other tab');
  });

  it('rejects a late open reply after another chat is selected', async () => {
    const api = new ApiClient();
    vi.spyOn(api, 'actorWorkspace').mockResolvedValue({
      revision: 0,
      last_investigation_id: null,
      host: 'local',
      model: null,
    });
    vi.spyOn(api, 'saveActorWorkspace').mockResolvedValue({
      revision: 1,
      last_investigation_id: id,
      host: 'local',
      model: null,
    });
    let finish: (value: typeof detail) => void = () => {};
    vi.spyOn(api, 'investigation')
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finish = resolve;
          }),
      )
      .mockResolvedValueOnce({ ...detail, id: '22222222-2222-4222-8222-222222222222' });
    const { result } = renderHook(() => useWorkspace(api));
    await waitFor(() => expect(result.current.ready).toBe(true));
    let older: Promise<void>;
    act(() => {
      older = result.current.open(id);
    });
    await act(async () => {
      await result.current.open('22222222-2222-4222-8222-222222222222');
    });
    await act(async () => {
      finish(detail);
      await older!;
    });
    expect(result.current.detail?.id).toBe('22222222-2222-4222-8222-222222222222');
  });
});
