import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { DemoClient } from './demo';
import { useInvestigation } from './useInvestigation';
import type { TurnEvent, TurnInput } from './contracts';

describe('host-scoped diagnostic session', () => {
  it('drops an expired session and reuses only the replacement session on subsequent turns', async () => {
    const inputs: TurnInput[] = [];
    const client = new DemoClient();
    const id = '4a59a145-0037-4934-92e0-f422105583b9';
    client.diagnose = async (input, receive) => {
      inputs.push(input);
      const envelope = { schema_version: 1 as const, request_id: 'r', turn_id: 't' };
      receive({ ...envelope, type: 'turn.started', session_id: id });
      receive(
        inputs.length === 1
          ? { ...envelope, type: 'turn.failed', code: 'session_not_found', message: 'Session expired' }
          : { ...envelope, type: 'turn.completed' },
      );
    };
    const { result } = renderHook(() => useInvestigation(client, 'local'));
    await act(() => result.current.run('First'));
    expect(result.current.turns[0]?.state).toBe('failed');
    await act(() => result.current.run('Retry'));
    await act(() => result.current.run('Continue'));
    expect(inputs[0]?.session_id).toBeUndefined();
    expect(inputs[1]?.session_id).toBeUndefined();
    expect(inputs[2]?.session_id).toBe(id);
  });

  it('ignores late events after stop and keeps a manual retry available', async () => {
    const client = new DemoClient();
    let late: ((event: TurnEvent) => void) | undefined;
    client.diagnose = async (_input, receive, signal) => {
      late = receive;
      await new Promise<void>((resolve) => signal.addEventListener('abort', () => resolve(), { once: true }));
    };
    const { result } = renderHook(() => useInvestigation(client, 'local'));
    act(() => {
      void result.current.run('Collect evidence');
    });
    await waitFor(() => expect(result.current.running).toBe(true));
    act(() => result.current.stop());
    act(() => late?.({ schema_version: 1, request_id: 'late', turn_id: 'late', type: 'turn.completed' }));
    expect(result.current.turns[0]?.state).toBe('stopped');
    expect(result.current.running).toBe(false);
  });
});
