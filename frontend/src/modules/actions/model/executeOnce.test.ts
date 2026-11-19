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

it('keeps a failed execution unconfirmed when its authoritative recovery read also fails', async () => {
  const failure = new TypeError('Execution response lost');
  const api = {
    execute: vi.fn().mockRejectedValue(failure),
    action: vi.fn().mockRejectedValue(new TypeError('Recovery read unavailable')),
  };

  await expect(executeOnce(api, 'action-1', 'original-key')).rejects.toMatchObject({
    message:
      'Execution response unavailable. The Docker result is unconfirmed. Check this existing action before retrying.',
    cause: failure,
  });
  expect(api.execute).toHaveBeenCalledOnce();
  expect(api.execute).toHaveBeenCalledWith('action-1', 'original-key');
  expect(api.action).toHaveBeenCalledOnce();
  expect(api.action).toHaveBeenCalledWith('action-1');
});
