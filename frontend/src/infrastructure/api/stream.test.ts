import { expect, it, vi } from 'vitest';
import type { SavedTurn } from '../../shared/contracts/investigation-contracts';
import { consumeSnapshots } from './stream';

/** Build a valid retained turn while varying only the observed lifecycle state. */
function snapshot(revision: number, state: SavedTurn['state']): SavedTurn {
  return {
    schema_version: 1,
    id: '11111111-1111-4111-8111-111111111111',
    investigation_id: '22222222-2222-4222-8222-222222222222',
    actor: 'operator',
    host: 'local',
    submission_id: '33333333-3333-4333-8333-333333333333',
    request_id: 'original-request',
    query: 'Original question',
    target: null,
    model: null,
    clarification_of: null,
    resolved_by_turn_id: null,
    state,
    revision,
    created_at: '2026-11-04T12:00:00Z',
    updated_at: '2026-11-04T12:00:00Z',
    finished_at: state === 'running' ? null : '2026-11-04T12:00:00Z',
    progress: [],
    progress_truncated: false,
    trace: [],
    answer: null,
    selection: null,
    error: null,
  };
}

/** Encode a full snapshot frame with its authoritative revision. */
function frame(turn: SavedTurn, id = String(turn.revision)): string {
  return `event: turn.snapshot\nid: ${id}\ndata: ${JSON.stringify(turn)}\n\n`;
}

it('coalesces duplicate revisions and retains the terminal snapshot across split frames', async () => {
  const running = snapshot(1, 'running');
  const completed = snapshot(2, 'completed');
  const bytes = new TextEncoder().encode(frame(running) + frame(running) + frame(completed));
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(bytes.slice(0, 17));
      controller.enqueue(bytes.slice(17));
      controller.close();
    },
  });
  const receive = vi.fn<(turn: SavedTurn) => void>();

  await consumeSnapshots(new Response(body), receive);

  expect(receive.mock.calls.map(([turn]) => turn.revision)).toEqual([1, 2]);
  expect(receive.mock.calls[1]?.[0].state).toBe('completed');
});

it('rejects a snapshot whose frame ID does not match its revision', async () => {
  const receive = vi.fn<(turn: SavedTurn) => void>();

  await expect(consumeSnapshots(new Response(frame(snapshot(1, 'running'), '2')), receive)).rejects.toThrow(
    'Unsupported observation revision.',
  );
  expect(receive).not.toHaveBeenCalled();
});

it('rejects an unsupported observation event without publishing it', async () => {
  const receive = vi.fn<(turn: SavedTurn) => void>();
  const unexpected = `event: turn.unknown\ndata: ${JSON.stringify(snapshot(1, 'running'))}\n\n`;

  await expect(consumeSnapshots(new Response(unexpected), receive)).rejects.toThrow('Unsupported observation event.');
  expect(receive).not.toHaveBeenCalled();
});

it('reports a disconnected running observation rather than inventing a terminal state', async () => {
  const running = snapshot(1, 'running');
  const receive = vi.fn<(turn: SavedTurn) => void>();

  await expect(consumeSnapshots(new Response(frame(running)), receive)).rejects.toThrow(
    'Observation disconnected. Reconnecting to the saved turn.',
  );
  expect(receive).toHaveBeenCalledOnce();
  expect(receive.mock.calls[0]?.[0]).toEqual(running);
});

it('rejects oversized observation data before publishing a snapshot', async () => {
  const receive = vi.fn<(turn: SavedTurn) => void>();

  await expect(consumeSnapshots(new Response('x'.repeat(2 * 1024 * 1024 + 1)), receive)).rejects.toThrow(
    'Diagnostic event exceeded the supported size.',
  );
  expect(receive).not.toHaveBeenCalled();
});

it('surfaces an explicit stream error without publishing a snapshot', async () => {
  const receive = vi.fn<(turn: SavedTurn) => void>();
  const failure = { schema_version: 1, code: 'unavailable', message: 'Observation unavailable' };

  await expect(
    consumeSnapshots(new Response(`event: error\ndata: ${JSON.stringify(failure)}\n\n`), receive),
  ).rejects.toThrow('Observation unavailable');
  expect(receive).not.toHaveBeenCalled();
});
