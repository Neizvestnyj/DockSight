import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { ApiClient } from './api';
import { useSavedInvestigations } from './useSavedInvestigations';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

it('keeps ten as a page size and deduplicates older pages without deleting chats', async () => {
  const api = new ApiClient();
  const rows = Array.from({ length: 11 }, (_, index) => ({
    id: String(index),
    title: `Question ${index}`,
    host: 'local',
    created_at: '2026-11-04T12:00:00Z',
    updated_at: '2026-11-04T12:00:00Z',
    turn_count: 1,
    active_turn_id: null,
  }));
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
