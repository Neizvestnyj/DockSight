import { expect, it, vi } from 'vitest';
import { executeOnce } from './executeOnce';

it('reads an existing action after lost response without resubmitting a mutation', async () => {
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
