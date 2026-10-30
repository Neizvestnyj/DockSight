import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { DemoClient, demoAnswer } from './demo';
import { useInvestigation } from './useInvestigation';
import type { GroupTarget, TurnEvent, TurnInput } from './contracts';

const target: GroupTarget = { kind: 'compose', name: 'vintoria-infra' };

/** Emit a complete scope-resolution response without manufacturing a diagnostic answer. */
function requireSelection(receive: (event: TurnEvent) => void) {
  const base = { schema_version: 1 as const, request_id: 'resolve-request', turn_id: 'resolve-turn' };
  receive({ ...base, type: 'tool.started', tool: 'resolve_target' });
  receive({ ...base, type: 'tool.completed', tool: 'resolve_target', ok: true });
  receive({ ...base, type: 'clarification.required', selection: { candidates: [target] } });
  receive({ ...base, type: 'turn.completed' });
}

describe('host-scoped diagnostic session', () => {
  it('continues a pending scope choice in one row and retains earlier answers', async () => {
    const inputs: TurnInput[] = [];
    const answer = demoAnswer('dependency', 'local');
    const client = new DemoClient();
    let oldEvents: ((event: TurnEvent) => void) | undefined;
    let finish = () => {};
    const gate = new Promise<void>((resolve) => {
      finish = resolve;
    });
    client.diagnose = async (input, receive) => {
      inputs.push(input);
      if (inputs.length === 1) {
        oldEvents = receive;
        requireSelection(receive);
        return;
      }
      const base = { schema_version: 1 as const, request_id: 'diagnose-request', turn_id: 'diagnose-turn' };
      receive({ ...base, type: 'tool.started', tool: 'inspect_group' });
      await gate;
      receive({ ...base, type: 'answer.ready', answer });
      receive({ ...base, type: 'turn.completed' });
    };
    const { result } = renderHook(() => useInvestigation(client, 'local', answer));
    await act(() => result.current.run('What happened?'));
    const id = result.current.turns[1]!.id;
    await act(() => result.current.chooseGroup(id, { kind: 'compose', name: 'unobserved-project' }));
    expect(inputs).toHaveLength(1);
    try {
      act(() => {
        void result.current.chooseGroup(id, target);
        void result.current.chooseGroup(id, target);
      });
      await waitFor(() => expect(result.current.running).toBe(true));
      expect(inputs).toHaveLength(2);
      expect(inputs[1]).toEqual({ host: 'local', query: 'What happened?', group: target });
      expect(result.current.turns).toHaveLength(2);
      expect(result.current.turns[1]).toMatchObject({
        id,
        group: target,
        state: 'running',
        requestId: 'diagnose-request',
        progress: [{ tool: 'inspect_group', state: 'running' }],
      });
      expect(result.current.turns[1]?.selection).toBeUndefined();
      act(() => oldEvents?.({ schema_version: 1, request_id: 'late', turn_id: 'late', type: 'turn.completed' }));
      expect(result.current.turns[1]?.state).toBe('running');
    } finally {
      await act(async () => finish());
    }
    await waitFor(() => expect(result.current.turns[1]?.state).toBe('completed'));
    expect(result.current.turns).toHaveLength(2);
    expect(result.current.turns[0]?.answer).toBe(answer);
    await act(() => result.current.chooseGroup(id, target));
    expect(inputs).toHaveLength(2);
    await act(() => result.current.run('A separate question'));
    expect(result.current.turns).toHaveLength(3);
  });

  it.each(['stopped', 'failed'] as const)('keeps a %s continuation on its original question', async (state) => {
    const client = new DemoClient();
    let events: ((event: TurnEvent) => void) | undefined;
    let finish = () => {};
    client.diagnose = async (input, receive) => {
      if (!input.group) {
        requireSelection(receive);
        return;
      }
      events = receive;
      await new Promise<void>((resolve) => {
        finish = resolve;
      });
    };
    const { result } = renderHook(() => useInvestigation(client, 'local'));
    await act(() => result.current.run('What happened?'));
    const id = result.current.turns[0]!.id;
    act(() => {
      void result.current.chooseGroup(id, target);
    });
    await waitFor(() => expect(result.current.running).toBe(true));
    if (state === 'stopped') act(() => result.current.stop());
    act(() =>
      events?.({
        schema_version: 1,
        request_id: 'r',
        turn_id: 't',
        type: 'turn.failed',
        code: 'provider_timeout',
        message: 'Timed out',
      }),
    );
    await act(async () => finish());
    expect(result.current.turns).toHaveLength(1);
    expect(result.current.turns[0]).toMatchObject({ id, state, group: target });
    expect(result.current.turns[0]?.selection).toBeUndefined();
  });

  it('starts a container diagnosis in a fresh session while retaining earlier answers', async () => {
    const inputs: TurnInput[] = [];
    const client = new DemoClient();
    const answer = demoAnswer('crash_loop', 'local');
    const id = '4a59a145-0037-4934-92e0-f422105583b9';
    client.diagnose = async (input, receive) => {
      inputs.push(input);
      const envelope = { schema_version: 1 as const, request_id: 'r', turn_id: 't' };
      receive({ ...envelope, type: 'turn.started', session_id: id });
      receive({ ...envelope, type: 'answer.ready', answer });
      receive({ ...envelope, type: 'turn.completed' });
    };
    const { result } = renderHook(() => useInvestigation(client, 'local'));
    await act(() => result.current.run('First'));
    await act(() => result.current.run('Container diagnosis', true));
    await act(() => result.current.run('Follow up'));
    expect(inputs[1]?.session_id).toBeUndefined();
    expect(inputs[2]?.session_id).toBe(id);
    expect(result.current.turns).toHaveLength(3);
    expect(result.current.turns[0]?.answer).toBe(answer);
  });
  it('distinguishes local transport errors from identical server-authored messages', async () => {
    const client = new DemoClient();
    const message = 'Connection ended before the diagnostic turn completed. Retry manually.';
    client.diagnose = async () => {
      throw new Error(message);
    };
    const { result } = renderHook(() => useInvestigation(client, 'local'));
    await act(() => result.current.run('First'));
    expect(result.current.turns[0]).toMatchObject({ errorSource: 'client', error: message });
    client.diagnose = async (_input, receive) =>
      receive({ schema_version: 1, request_id: 'r', turn_id: 't', type: 'turn.failed', code: 'upstream', message });
    await act(() => result.current.run('Retry'));
    expect(result.current.turns[1]).toMatchObject({ errorSource: 'server', error: message });
  });
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
