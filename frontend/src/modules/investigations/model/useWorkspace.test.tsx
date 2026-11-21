import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiClient } from '../../../infrastructure/api/api';
import { ApiError } from '../../../shared/contracts/errors';
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
  it('keeps a failed first draft local and retries creation with the same ID', async () => {
    const api = new ApiClient();
    vi.spyOn(api, 'actorWorkspace').mockResolvedValue({
      revision: 0,
      last_investigation_id: null,
      host: 'local',
      model: null,
    });
    vi.spyOn(api, 'saveActorWorkspace').mockImplementation(async (_, changes) => ({
      revision: 1,
      last_investigation_id: changes.last_investigation_id ?? null,
      host: 'local',
      model: null,
    }));
    let reject!: (reason: Error) => void;
    const create = vi
      .spyOn(api, 'createInvestigation')
      .mockImplementationOnce(() => new Promise((_resolve, fail) => (reject = fail)))
      .mockImplementation(async (draftId) => ({ ...detail, id: draftId }));
    const writes = vi.spyOn(api, 'saveWorkspace').mockResolvedValue({ ...empty, revision: 1, draft: 'Latest draft' });
    const refresh = vi.fn(async () => {});
    const { result } = renderHook(() => useWorkspace(api, refresh));
    await waitFor(() => expect(result.current.ready).toBe(true));
    await act(async () => {
      expect(await result.current.beginDraft('local')).toBe(true);
    });
    const draftId = result.current.draftChat?.id;
    await act(async () => {
      expect(await result.current.beginDraft('local')).toBe(true);
      result.current.setDraft(' ');
    });
    expect(result.current.draftChat?.id).toBe(draftId);
    expect(create).not.toHaveBeenCalled();
    await act(async () => {
      result.current.setDraft('First text');
      result.current.setDraft('Latest draft');
    });
    expect(create).toHaveBeenCalledExactlyOnceWith(draftId, 'local');
    await act(async () => reject(new Error('offline')));
    expect(result.current.error).toBe('Could not create saved chat. Retry manually.');
    expect(result.current.draft).toBe('Latest draft');
    await act(async () => {
      expect(await result.current.beginDraft('local')).toBe(false);
      await result.current.saveNewDraft();
      await result.current.flush();
    });
    expect(create.mock.calls[1]).toEqual([draftId, 'local']);
    expect(writes).toHaveBeenCalledExactlyOnceWith(draftId, 0, { draft: 'Latest draft' });
    expect(refresh).toHaveBeenCalledOnce();
    expect(result.current.draftChat).toBeUndefined();
  });

  it('keeps an exact diagnosis and text entered during the same local chat creation', async () => {
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
    let acknowledge!: (value: typeof detail) => void;
    const create = vi.spyOn(api, 'createInvestigation').mockImplementation(
      () =>
        new Promise((resolve) => {
          acknowledge = resolve;
        }),
    );
    const target = { kind: 'compose', name: 'commerce' } as const;
    const writes = vi
      .spyOn(api, 'saveWorkspace')
      .mockResolvedValue({ ...empty, revision: 1, target, draft: 'Another question' });
    const { result } = renderHook(() => useWorkspace(api));
    await waitFor(() => expect(result.current.ready).toBe(true));
    await act(async () => {
      await result.current.beginDraft('local');
      result.current.patch({ target });
    });
    const draftId = result.current.draftChat!.id;
    expect(create).not.toHaveBeenCalled();
    let starting!: Promise<void>;
    await act(async () => {
      starting = result.current.create('local', { query: 'Inspect commerce', target });
    });
    await act(async () => result.current.setDraft('Another question'));
    await act(async () => {
      acknowledge({ ...detail, id: draftId });
      await starting;
      expect(result.current.takeDiagnosis(draftId)).toMatchObject({ query: 'Inspect commerce', target });
      expect(result.current.takeDiagnosis(draftId)).toBeUndefined();
      await result.current.flush();
    });
    expect(create).toHaveBeenCalledExactlyOnceWith(draftId, 'local');
    expect(writes).toHaveBeenCalledExactlyOnceWith(draftId, 0, { target, draft: 'Another question' });
  });

  it('does not write a provisional draft or preferences after its owner unmounts during creation', async () => {
    const api = new ApiClient();
    vi.spyOn(api, 'actorWorkspace').mockResolvedValue({
      revision: 0,
      last_investigation_id: null,
      host: null,
      model: null,
    });
    const preferences = vi.spyOn(api, 'saveActorWorkspace').mockResolvedValue({
      revision: 1,
      last_investigation_id: id,
      host: 'local',
      model: null,
    });
    const writes = vi.spyOn(api, 'saveWorkspace').mockResolvedValue({ ...empty, revision: 1 });
    let acknowledge: (value: typeof detail) => void = () => {};
    vi.spyOn(api, 'createInvestigation').mockImplementation(
      () =>
        new Promise((resolve) => {
          acknowledge = resolve;
        }),
    );
    const { result, unmount } = renderHook(() => useWorkspace(api));
    await waitFor(() => expect(result.current.ready).toBe(true));
    vi.useFakeTimers();
    let creating: Promise<void>;
    act(() => {
      creating = result.current.create('local');
    });
    await act(async () => {
      await Promise.resolve();
    });
    act(() => result.current.setDraft('Pending old connection draft'));
    unmount();
    expect(preferences).not.toHaveBeenCalled();
    expect(writes).not.toHaveBeenCalled();
    await act(async () => {
      acknowledge(detail);
      await creating!;
      await vi.advanceTimersByTimeAsync(350);
    });
    expect(preferences).not.toHaveBeenCalled();
    expect(writes).not.toHaveBeenCalled();
  });

  it('retains an initial draft and saves it 300 ms after chat acknowledgement', async () => {
    const api = new ApiClient();
    vi.spyOn(api, 'actorWorkspace').mockResolvedValue({
      revision: 0,
      last_investigation_id: null,
      host: null,
      model: null,
    });
    vi.spyOn(api, 'saveActorWorkspace').mockResolvedValue({
      revision: 1,
      last_investigation_id: id,
      host: 'local',
      model: null,
    });
    let acknowledge: (value: typeof detail) => void = () => {};
    vi.spyOn(api, 'createInvestigation').mockImplementation(
      () =>
        new Promise((resolve) => {
          acknowledge = resolve;
        }),
    );
    const writes = vi.spyOn(api, 'saveWorkspace').mockImplementation(async (_id, revision, changes) => ({
      ...empty,
      revision: revision + 1,
      draft: changes.draft ?? '',
    }));
    const { result } = renderHook(() => useWorkspace(api));
    await waitFor(() => expect(result.current.ready).toBe(true));
    vi.useFakeTimers();
    let creating: Promise<void>;
    act(() => {
      creating = result.current.create('local');
    });
    await act(async () => {
      await Promise.resolve();
    });
    act(() => result.current.setDraft('Typed during startup'));
    expect(result.current.draft).toBe('Typed during startup');
    expect(result.current.saveState).toBe('unsaved');
    expect(writes).not.toHaveBeenCalled();
    await act(async () => {
      acknowledge(detail);
      await creating!;
    });
    expect(result.current.draft).toBe('Typed during startup');
    expect(result.current.saveState).toBe('unsaved');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(299);
    });
    expect(writes).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(writes).toHaveBeenCalledWith(id, 0, { draft: 'Typed during startup' });
    expect(result.current.saveState).toBe('saved');
  });

  it('retains an initial draft on creation failure and saves it on a same-host retry', async () => {
    const api = new ApiClient();
    vi.spyOn(api, 'actorWorkspace').mockResolvedValue({
      revision: 0,
      last_investigation_id: null,
      host: null,
      model: null,
    });
    vi.spyOn(api, 'saveActorWorkspace').mockResolvedValue({
      revision: 1,
      last_investigation_id: id,
      host: 'local',
      model: null,
    });
    let rejectCreate: (error: Error) => void = () => {};
    vi.spyOn(api, 'createInvestigation')
      .mockImplementationOnce(
        () =>
          new Promise((_resolve, reject) => {
            rejectCreate = reject;
          }),
      )
      .mockResolvedValueOnce(detail);
    const writes = vi.spyOn(api, 'saveWorkspace').mockImplementation(async (_id, revision, changes) => ({
      ...empty,
      revision: revision + 1,
      draft: changes.draft ?? '',
    }));
    const { result } = renderHook(() => useWorkspace(api));
    await waitFor(() => expect(result.current.ready).toBe(true));
    let creating: Promise<void>;
    act(() => {
      creating = result.current.create('local');
    });
    await act(async () => {
      await Promise.resolve();
    });
    act(() => result.current.setDraft('Keep after failure'));
    await act(async () => {
      rejectCreate(new Error('offline'));
      await creating!;
    });
    expect(result.current.draft).toBe('Keep after failure');
    expect(result.current.saveState).toBe('unsaved');
    expect(result.current.error).toBe('Could not create saved chat. Retry manually.');
    expect(writes).not.toHaveBeenCalled();
    await act(async () => {
      await result.current.create('local');
    });
    expect(result.current.draft).toBe('Keep after failure');
    await act(async () => {
      await result.current.flush();
    });
    expect(writes).toHaveBeenCalledWith(id, 0, { draft: 'Keep after failure' });
  });

  it('does not install an initial draft into a different chat after a late creation reply', async () => {
    const api = new ApiClient();
    const other = {
      ...detail,
      id: '22222222-2222-4222-8222-222222222222',
      workspace: { ...empty, draft: 'Other chat' },
    };
    vi.spyOn(api, 'actorWorkspace').mockResolvedValue({
      revision: 0,
      last_investigation_id: null,
      host: null,
      model: null,
    });
    vi.spyOn(api, 'saveActorWorkspace').mockResolvedValue({
      revision: 1,
      last_investigation_id: other.id,
      host: 'local',
      model: null,
    });
    vi.spyOn(api, 'investigation').mockResolvedValue(other);
    let acknowledge: (value: typeof detail) => void = () => {};
    vi.spyOn(api, 'createInvestigation').mockImplementation(
      () =>
        new Promise((resolve) => {
          acknowledge = resolve;
        }),
    );
    const writes = vi.spyOn(api, 'saveWorkspace');
    const { result } = renderHook(() => useWorkspace(api));
    await waitFor(() => expect(result.current.ready).toBe(true));
    let creating: Promise<void>;
    act(() => {
      creating = result.current.create('local');
    });
    await act(async () => {
      await Promise.resolve();
    });
    act(() => result.current.setDraft('First scope only'));
    expect(result.current.draft).toBe('First scope only');
    await act(async () => {
      await result.current.open(other.id);
    });
    await act(async () => {
      acknowledge(detail);
      await creating!;
    });
    expect(result.current.detail?.id).toBe(other.id);
    expect(result.current.draft).toBe('Other chat');
    expect(writes).not.toHaveBeenCalled();
  });

  it('retains the initial draft if navigation to another chat fails', async () => {
    const api = new ApiClient();
    vi.spyOn(api, 'actorWorkspace').mockResolvedValue({
      revision: 0,
      last_investigation_id: null,
      host: null,
      model: null,
    });
    vi.spyOn(api, 'investigation').mockRejectedValue(new Error('offline'));
    vi.spyOn(api, 'saveActorWorkspace').mockResolvedValue({
      revision: 1,
      last_investigation_id: id,
      host: 'local',
      model: null,
    });
    const creates = vi.spyOn(api, 'createInvestigation').mockResolvedValue(detail);
    const writes = vi.spyOn(api, 'saveWorkspace').mockImplementation(async (_id, revision, changes) => ({
      ...empty,
      revision: revision + 1,
      draft: changes.draft ?? '',
    }));
    const { result } = renderHook(() => useWorkspace(api));
    await waitFor(() => expect(result.current.ready).toBe(true));
    act(() => result.current.setDraft('Keep after failed navigation'));
    await act(async () => {
      await result.current.open(id);
    });
    expect(result.current.draft).toBe('Keep after failed navigation');
    expect(result.current.saveState).toBe('unsaved');
    expect(creates).not.toHaveBeenCalled();
    await act(async () => {
      await result.current.create('local');
      await result.current.flush();
    });
    expect(writes).toHaveBeenCalledWith(id, 0, { draft: 'Keep after failed navigation' });
  });

  it('does not carry an unacknowledged initial draft into another connection', async () => {
    const first = new ApiClient();
    const second = new ApiClient();
    vi.spyOn(first, 'actorWorkspace').mockResolvedValue({
      revision: 0,
      last_investigation_id: null,
      host: null,
      model: null,
    });
    let acknowledge: (value: typeof detail) => void = () => {};
    vi.spyOn(first, 'createInvestigation').mockImplementation(
      () =>
        new Promise((resolve) => {
          acknowledge = resolve;
        }),
    );
    vi.spyOn(second, 'actorWorkspace').mockResolvedValue({
      revision: 0,
      last_investigation_id: id,
      host: 'local',
      model: null,
    });
    vi.spyOn(second, 'investigation').mockResolvedValue({ ...detail, workspace: { ...empty, draft: 'Second actor' } });
    const writes = vi.spyOn(second, 'saveWorkspace');
    const { result, rerender } = renderHook(({ api }) => useWorkspace(api), { initialProps: { api: first } });
    await waitFor(() => expect(result.current.ready).toBe(true));
    let creating: Promise<void>;
    act(() => {
      creating = result.current.create('local');
    });
    await act(async () => {
      await Promise.resolve();
    });
    act(() => result.current.setDraft('First actor only'));
    expect(result.current.draft).toBe('First actor only');
    rerender({ api: second });
    await waitFor(() => expect(result.current.draft).toBe('Second actor'));
    await act(async () => {
      acknowledge(detail);
      await creating!;
    });
    expect(result.current.draft).toBe('Second actor');
    expect(result.current.loading).toBe(false);
    expect(writes).not.toHaveBeenCalled();
  });

  it('retains an initial draft as unsaved when its first revisioned write fails', async () => {
    const api = new ApiClient();
    vi.spyOn(api, 'actorWorkspace').mockResolvedValue({
      revision: 0,
      last_investigation_id: null,
      host: null,
      model: null,
    });
    vi.spyOn(api, 'saveActorWorkspace').mockResolvedValue({
      revision: 1,
      last_investigation_id: id,
      host: 'local',
      model: null,
    });
    vi.spyOn(api, 'createInvestigation').mockResolvedValue(detail);
    const writes = vi.spyOn(api, 'saveWorkspace').mockRejectedValueOnce(new Error('offline'));
    const { result } = renderHook(() => useWorkspace(api));
    await waitFor(() => expect(result.current.ready).toBe(true));
    act(() => result.current.setDraft('Keep until saved'));
    await act(async () => {
      await result.current.create('local');
    });
    await act(async () => {
      await result.current.flush();
    });
    expect(writes).toHaveBeenCalledWith(id, 0, { draft: 'Keep until saved' });
    expect(result.current.draft).toBe('Keep until saved');
    expect(result.current.saveState).toBe('error');
    expect(result.current.detail?.workspace.draft).toBe('');
    expect(result.current.revision()).toBe(0);
  });

  it('does not send an earlier initial draft to a later creation on another host', async () => {
    const api = new ApiClient();
    vi.spyOn(api, 'actorWorkspace').mockResolvedValue({
      revision: 0,
      last_investigation_id: null,
      host: null,
      model: null,
    });
    vi.spyOn(api, 'saveActorWorkspace').mockResolvedValue({
      revision: 1,
      last_investigation_id: id,
      host: 'remote',
      model: null,
    });
    let acknowledge: (value: typeof detail) => void = () => {};
    vi.spyOn(api, 'createInvestigation')
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            acknowledge = resolve;
          }),
      )
      .mockResolvedValueOnce({ ...detail, host: 'remote' });
    const writes = vi.spyOn(api, 'saveWorkspace');
    const { result } = renderHook(() => useWorkspace(api));
    await waitFor(() => expect(result.current.ready).toBe(true));
    let first: Promise<void>;
    act(() => {
      first = result.current.create('local');
    });
    await act(async () => {
      await Promise.resolve();
    });
    act(() => result.current.setDraft('Local host only'));
    expect(result.current.draft).toBe('Local host only');
    await act(async () => {
      await result.current.create('remote');
    });
    await act(async () => {
      acknowledge(detail);
      await first!;
    });
    expect(result.current.detail?.host).toBe('remote');
    expect(result.current.draft).toBe('');
    expect(writes).not.toHaveBeenCalled();
  });

  it('does not restore an initial draft that was never acknowledged after reconnecting', async () => {
    const api = new ApiClient();
    vi.spyOn(api, 'actorWorkspace').mockResolvedValue({
      revision: 0,
      last_investigation_id: null,
      host: null,
      model: null,
    });
    let acknowledge: (value: typeof detail) => void = () => {};
    vi.spyOn(api, 'createInvestigation').mockImplementation(
      () =>
        new Promise((resolve) => {
          acknowledge = resolve;
        }),
    );
    const writes = vi.spyOn(api, 'saveWorkspace');
    const first = renderHook(() => useWorkspace(api));
    await waitFor(() => expect(first.result.current.ready).toBe(true));
    let creating: Promise<void>;
    act(() => {
      creating = first.result.current.create('local');
    });
    await act(async () => {
      await Promise.resolve();
    });
    act(() => first.result.current.setDraft('Not acknowledged'));
    expect(first.result.current.draft).toBe('Not acknowledged');
    first.unmount();
    const restored = renderHook(() => useWorkspace(api));
    await waitFor(() => expect(restored.result.current.ready).toBe(true));
    await act(async () => {
      acknowledge(detail);
      await creating!;
    });
    expect(restored.result.current.draft).toBe('');
    expect(writes).not.toHaveBeenCalled();
  });

  it.each(['same', 'other', 'new'])('saves edits typed while %s navigation is reading', async (navigation) => {
    const api = new ApiClient();
    vi.spyOn(api, 'actorWorkspace').mockResolvedValue({
      revision: 0,
      last_investigation_id: id,
      host: 'local',
      model: null,
    });
    vi.spyOn(api, 'saveActorWorkspace').mockResolvedValue({
      revision: 1,
      last_investigation_id: id,
      host: 'local',
      model: null,
    });
    let release: (value: typeof detail) => void = () => {};
    const reading = () =>
      new Promise<typeof detail>((resolve) => {
        release = resolve;
      });
    const reads = vi.spyOn(api, 'investigation').mockResolvedValueOnce(detail).mockImplementation(reading);
    const creates = vi.spyOn(api, 'createInvestigation').mockImplementation(reading);
    const writes: string[] = [];
    vi.spyOn(api, 'saveWorkspace').mockImplementation(async (_id, revision, changes) => {
      writes.push(changes.draft ?? '');
      return { ...empty, revision: revision + 1, draft: changes.draft ?? '' };
    });
    const { result } = renderHook(() => useWorkspace(api));
    await waitFor(() => expect(result.current.ready).toBe(true));
    let navigating: Promise<void | boolean>;
    act(() => {
      result.current.setDraft('First edit');
      navigating =
        navigation === 'new'
          ? result.current.create('local')
          : result.current.open(navigation === 'same' ? id : '22222222-2222-4222-8222-222222222222');
    });
    await waitFor(() =>
      expect(navigation === 'new' ? creates : reads).toHaveBeenCalledTimes(navigation === 'new' ? 1 : 2),
    );
    act(() => result.current.setDraft('Typed during navigation'));
    await act(async () => {
      release({
        ...detail,
        id: navigation === 'same' ? id : '22222222-2222-4222-8222-222222222222',
        workspace: { ...empty, revision: 1, draft: 'First edit' },
      });
      await navigating!;
    });
    expect(writes).toEqual(['First edit', 'Typed during navigation']);
    if (navigation === 'same') expect(result.current.draft).toBe('Typed during navigation');
  });

  it.each(['same', 'other', 'new', 'host'])('saves pending text before %s navigation', async (navigation) => {
    const api = new ApiClient();
    vi.spyOn(api, 'actorWorkspace').mockResolvedValue({
      revision: 0,
      last_investigation_id: id,
      host: 'local',
      model: null,
    });
    vi.spyOn(api, 'saveActorWorkspace').mockResolvedValue({
      revision: 1,
      last_investigation_id: id,
      host: 'local',
      model: null,
    });
    const events: string[] = [];
    vi.spyOn(api, 'investigation')
      .mockImplementation(async (identity) => {
        events.push('read');
        return {
          ...detail,
          id: identity,
          workspace: identity === id ? { ...empty, revision: 1, draft: 'Pending text' } : empty,
        };
      })
      .mockResolvedValueOnce(detail);
    vi.spyOn(api, 'createInvestigation').mockImplementation(async (identity, host) => {
      events.push('create');
      return { ...detail, id: identity, host };
    });
    vi.spyOn(api, 'saveWorkspace').mockImplementation(async () => {
      events.push('save');
      return { ...empty, revision: 1, draft: 'Pending text' };
    });
    const { result } = renderHook(() => useWorkspace(api));
    await waitFor(() => expect(result.current.ready).toBe(true));
    act(() => result.current.setDraft('Pending text'));
    await act(async () => {
      if (navigation === 'new' || navigation === 'host')
        await result.current.create(navigation === 'host' ? 'remote' : 'local');
      else await result.current.open(navigation === 'same' ? id : '22222222-2222-4222-8222-222222222222');
    });
    expect(events).toEqual(['save', navigation === 'new' || navigation === 'host' ? 'create' : 'read']);
    if (navigation === 'same') expect(result.current.draft).toBe('Pending text');
  });

  it.each(['same', 'other', 'new', 'host'])('retains conflict and draft during %s navigation', async (navigation) => {
    const api = new ApiClient();
    vi.spyOn(api, 'actorWorkspace').mockResolvedValue({
      revision: 0,
      last_investigation_id: id,
      host: 'local',
      model: null,
    });
    const reads = vi.spyOn(api, 'investigation').mockResolvedValue(detail);
    const creates = vi.spyOn(api, 'createInvestigation').mockResolvedValue(detail);
    vi.spyOn(api, 'saveActorWorkspace').mockResolvedValue({
      revision: 1,
      last_investigation_id: id,
      host: 'local',
      model: null,
    });
    const { result } = renderHook(() => useWorkspace(api));
    await waitFor(() => expect(result.current.ready).toBe(true));
    act(() => {
      result.current.setDraft('Keep this text');
      result.current.conflictWith({ ...empty, revision: 1, draft: 'Remote text' });
    });
    await act(async () => {
      if (navigation === 'new' || navigation === 'host')
        await result.current.create(navigation === 'host' ? 'remote' : 'local');
      else await result.current.open(navigation === 'same' ? id : '22222222-2222-4222-8222-222222222222');
    });
    expect(result.current.detail?.id).toBe(id);
    expect(result.current.draft).toBe('Keep this text');
    expect(result.current.saveState).toBe('conflict');
    expect(reads).toHaveBeenCalledTimes(1);
    expect(creates).not.toHaveBeenCalled();
  });

  it('retains workspace and local text when the navigation save fails', async () => {
    const api = new ApiClient();
    vi.spyOn(api, 'actorWorkspace').mockResolvedValue({
      revision: 0,
      last_investigation_id: id,
      host: 'local',
      model: null,
    });
    const reads = vi.spyOn(api, 'investigation').mockResolvedValue(detail);
    vi.spyOn(api, 'saveWorkspace').mockRejectedValue(new Error('offline'));
    vi.spyOn(api, 'saveActorWorkspace').mockResolvedValue({
      revision: 1,
      last_investigation_id: id,
      host: 'local',
      model: null,
    });
    const { result } = renderHook(() => useWorkspace(api));
    await waitFor(() => expect(result.current.ready).toBe(true));
    act(() => result.current.setDraft('Keep this text'));
    await act(async () => {
      await result.current.open('22222222-2222-4222-8222-222222222222');
    });
    expect(result.current.detail?.id).toBe(id);
    expect(result.current.draft).toBe('Keep this text');
    expect(result.current.saveState).toBe('error');
    expect(reads).toHaveBeenCalledTimes(1);
  });

  it('remembers removed-host archives without overwriting the valid preferred host', async () => {
    const api = new ApiClient();
    let preferences = { revision: 0, last_investigation_id: null as string | null, host: 'local', model: null };
    vi.spyOn(api, 'actorWorkspace').mockImplementation(async () => preferences);
    vi.spyOn(api, 'investigation').mockResolvedValue({ ...detail, host: 'removed' });
    vi.spyOn(api, 'saveActorWorkspace').mockImplementation(async (revision, changes) => {
      if (changes.host === 'removed') throw new Error('host removed');
      preferences = { ...preferences, ...changes, host: preferences.host, model: null, revision: revision + 1 };
      return preferences;
    });
    const first = renderHook(() => useWorkspace(api));
    await waitFor(() => expect(first.result.current.ready).toBe(true));
    await act(async () => {
      await first.result.current.open(id);
    });
    expect(preferences.last_investigation_id).toBe(id);
    expect(preferences.host).toBe('local');
    first.unmount();
    const restored = renderHook(() => useWorkspace(api));
    await waitFor(() => expect(restored.result.current.ready).toBe(true));
    expect(restored.result.current.detail?.id).toBe(id);
    expect(restored.result.current.detail?.host).toBe('removed');
  });

  it('settles its own in-flight save before comparing a refreshed workspace revision', async () => {
    const api = new ApiClient();
    vi.spyOn(api, 'actorWorkspace').mockResolvedValue({
      revision: 0,
      last_investigation_id: id,
      host: 'local',
      model: null,
    });
    const own = { ...detail, workspace: { ...empty, revision: 1, draft: 'My local draft' } };
    vi.spyOn(api, 'investigation').mockResolvedValueOnce(detail).mockResolvedValue(own);
    let acknowledge: (value: typeof empty) => void = () => {};
    vi.spyOn(api, 'saveWorkspace').mockImplementation(
      () =>
        new Promise((resolve) => {
          acknowledge = resolve;
        }),
    );
    const { result } = renderHook(() => useWorkspace(api));
    await waitFor(() => expect(result.current.ready).toBe(true));
    let saving: Promise<boolean>;
    let refreshing: Promise<void>;
    act(() => {
      result.current.setDraft('My local draft');
      saving = result.current.flush();
      refreshing = result.current.refresh();
    });
    await act(async () => {
      acknowledge(own.workspace);
      await saving!;
      await refreshing!;
    });
    expect(result.current.revision()).toBe(1);
    expect(result.current.saveState).toBe('saved');
    expect(result.current.draft).toBe('My local draft');
  });

  it('requires explicit conflict resolution when refresh advances a dirty draft revision', async () => {
    const api = new ApiClient();
    vi.spyOn(api, 'actorWorkspace').mockResolvedValue({
      revision: 0,
      last_investigation_id: id,
      host: 'local',
      model: null,
    });
    const remote = { ...detail, workspace: { ...empty, revision: 1, draft: 'Another tab draft' } };
    vi.spyOn(api, 'investigation').mockResolvedValueOnce(detail).mockResolvedValue(remote);
    const writes: string[] = [];
    vi.spyOn(api, 'saveWorkspace').mockImplementation(async (_id, revision, changes) => {
      writes.push(`${revision}:${changes.draft}`);
      return { ...remote.workspace, ...changes, revision: revision + 1 };
    });
    const { result } = renderHook(() => useWorkspace(api));
    await waitFor(() => expect(result.current.ready).toBe(true));
    vi.useFakeTimers();
    act(() => result.current.setDraft('My local draft'));
    await act(async () => {
      await result.current.refresh();
      await result.current.flush();
    });
    expect(writes).toEqual([]);
    expect(result.current.revision()).toBe(0);
    expect(result.current.draft).toBe('My local draft');
    expect(result.current.saveState).toBe('conflict');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(writes).toEqual([]);
    await act(async () => {
      await result.current.useDraft();
    });
    expect(writes).toEqual(['1:My local draft']);
    expect(result.current.saveState).toBe('saved');
  });

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
    let older: Promise<boolean>;
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
