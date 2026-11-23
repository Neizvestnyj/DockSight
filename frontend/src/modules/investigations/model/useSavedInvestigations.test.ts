import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { ApiClient } from '../../../infrastructure/api/api';
import { ApiError } from '../../../shared/contracts/errors';
import type { InvestigationSummary } from '../../../shared/contracts/investigation-contracts';
import { useSavedInvestigations } from './useSavedInvestigations';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

/** Build a saved chat summary with an optional active diagnosis. */
function chat(id: string, active_turn_id: string | null = null): InvestigationSummary {
  return {
    id,
    title: `Question ${id}`,
    host: 'local',
    created_at: '2026-11-04T12:00:00Z',
    updated_at: '2026-11-04T12:00:00Z',
    turn_count: 1,
    active_turn_id,
  };
}

it('keeps ten as a page size and deduplicates older pages without deleting chats', async () => {
  const api = new ApiClient();
  const rows = Array.from({ length: 11 }, (_, index) => chat(String(index)));
  vi.spyOn(api, 'investigations')
    .mockResolvedValueOnce({ items: rows.slice(0, 10), next_cursor: 'older' })
    .mockResolvedValueOnce({ items: rows.slice(9), next_cursor: null });
  const remove = vi.spyOn(api, 'deleteInvestigation');
  const { result } = renderHook(() => useSavedInvestigations(api));
  await waitFor(() => expect(result.current.items).toHaveLength(10));
  await act(async () => {
    await result.current.older();
  });
  expect(result.current.items).toHaveLength(11);
  expect(result.current.nextCursor).toBeNull();
  expect(remove).not.toHaveBeenCalled();
});

it('keeps a loaded older page through refresh and retries its next cursor after a failed read', async () => {
  const api = new ApiClient();
  const recent = chat('recent');
  const middle = chat('middle');
  const oldest = chat('oldest');
  const updated = { ...recent, title: 'Updated question' };
  const list = vi
    .spyOn(api, 'investigations')
    .mockResolvedValueOnce({ items: [recent], next_cursor: 'middle-page' })
    .mockResolvedValueOnce({ items: [middle], next_cursor: 'oldest-page' })
    .mockResolvedValueOnce({ items: [updated], next_cursor: 'middle-page' })
    .mockRejectedValueOnce(new TypeError('Network unavailable'))
    .mockResolvedValueOnce({ items: [oldest], next_cursor: null });
  const { result } = renderHook(() => useSavedInvestigations(api));
  await waitFor(() => expect(result.current.items).toEqual([recent]));
  await act(() => result.current.older());
  act(() => {
    window.dispatchEvent(new Event('focus'));
  });
  await waitFor(() => expect(result.current.items).toEqual([updated, middle]));

  await act(() => result.current.older());
  expect(result.current.error).toBe('Could not load saved chats.');
  expect(result.current.items).toEqual([updated, middle]);
  expect(result.current.nextCursor).toBe('oldest-page');

  await act(() => result.current.older());
  expect(list.mock.calls.map(([, cursor]) => cursor)).toEqual([
    undefined,
    'middle-page',
    undefined,
    'oldest-page',
    'oldest-page',
  ]);
  expect(result.current.error).toBe('');
  expect(result.current.items).toEqual([updated, middle, oldest]);
  expect(result.current.nextCursor).toBeNull();
});

it('clears completed or deleted activity while keeping a chat whose activity read failed', async () => {
  const api = new ApiClient();
  const completed = chat('completed', 'turn-1');
  const deleted = chat('deleted', 'turn-2');
  const unreachable = chat('unreachable', 'turn-3');
  const idle = chat('idle');
  vi.spyOn(api, 'investigations').mockResolvedValue({
    items: [completed, deleted, unreachable, idle],
    next_cursor: null,
  });
  const read = vi.spyOn(api, 'investigation').mockImplementation(async (id) => {
    if (id === deleted.id) throw new ApiError('Chat unavailable', 'history_not_found');
    if (id === unreachable.id) throw new TypeError('Network unavailable');
    return {
      ...completed,
      active_turn_id: null,
      workspace: { revision: 0, draft: '', target: null, selected_container: null, view: 'diagnostics' },
      turns: { items: [], next_cursor: null },
    };
  });
  const { result } = renderHook(() => useSavedInvestigations(api));
  await waitFor(() =>
    expect(result.current.items.map((row) => row.active_turn_id)).toEqual([null, null, 'turn-3', null]),
  );
  expect(new Set(read.mock.calls.map(([id]) => id))).toEqual(new Set([completed.id, deleted.id, unreachable.id]));
});

it('keeps a chat visible after a refused delete and removes only the selected chat after server approval', async () => {
  const api = new ApiClient();
  const selected = chat('selected');
  const other = chat('other');
  const list = vi
    .spyOn(api, 'investigations')
    .mockResolvedValueOnce({ items: [selected, other], next_cursor: null })
    .mockResolvedValueOnce({ items: [other], next_cursor: null });
  const remove = vi
    .spyOn(api, 'deleteInvestigation')
    .mockRejectedValueOnce(new ApiError('Diagnosis is running', 'turn_busy'))
    .mockResolvedValueOnce(undefined);
  const { result } = renderHook(() => useSavedInvestigations(api));
  await waitFor(() => expect(result.current.items).toEqual([selected, other]));

  await act(async () => expect(await result.current.remove(selected.id)).toBe(false));
  expect(result.current.error).toMatch(/could not delete chat/i);
  expect(result.current.items).toEqual([selected, other]);
  expect(list).toHaveBeenCalledOnce();

  await act(async () => expect(await result.current.remove(selected.id)).toBe(true));
  expect(remove.mock.calls).toEqual([[selected.id], [selected.id]]);
  expect(result.current.items).toEqual([other]);
  expect(result.current.error).toBe('');
});
