import { act, cleanup, fireEvent, render, renderHook, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { eventSchema, type TraceStep } from './contracts';
import { DemoClient } from './demo';
import { useInvestigation } from './useInvestigation';
import App from './App';
import { DiagnosticTrace } from './DiagnosticTrace';

const envelope = { schema_version: 1, request_id: 'request-1', turn_id: 'turn-1' } as const;
const step: TraceStep = {
  id: 'step-1',
  kind: 'model',
  operation: 'final_response',
  state: 'running',
  started_at: '2026-10-28T09:00:00Z',
  finished_at: null,
  duration_ms: null,
  input_tokens: null,
  output_tokens: null,
  code: null,
  issues: [],
  response: null,
  response_truncated: false,
};

afterEach(cleanup);

describe('diagnostic trace transport and retention', () => {
  it('keeps historical answers usable when no trace was recorded', async () => {
    render(<App />);
    fireEvent.click(await screen.findByText('Diagnostic trace'));
    expect(
      screen
        .getByText('No trace was recorded for this turn. Run a new diagnosis to capture its steps.')
        .closest('details')?.open,
    ).toBe(true);
    expect(screen.getByText('Diagnostic conclusion')).toBeTruthy();
  });

  it('renders proposal markup as text and copies only the sanitized trace without the operator query', async () => {
    let copied = '';
    vi.stubGlobal('navigator', {
      clipboard: {
        writeText: async (value: string) => {
          copied = value;
        },
      },
    });
    try {
      const { container } = render(
        <DiagnosticTrace
          host="local"
          demo={false}
          turn={{
            id: 'local-id',
            query: 'private operator query',
            state: 'completed',
            progress: [],
            requestId: 'r',
            serverTurnId: 't',
            trace: {
              provider: 'ollama',
              model: 'qwen',
              started_at: step.started_at,
              steps: [
                {
                  ...step,
                  state: 'succeeded',
                  finished_at: '2026-10-28T09:00:00.500Z',
                  duration_ms: 500,
                  output_tokens: 0,
                  response: '<img src=x onerror=alert(1)>',
                },
              ],
            },
          }}
        />,
      );
      fireEvent.click(screen.getByText('Diagnostic trace'));
      fireEvent.click(screen.getByRole('button', { name: /Generating the final response/ }));
      fireEvent.click(screen.getByRole('button', { name: 'Back to steps' }));
      expect(container.querySelector('.trace-layout')?.classList.contains('show-detail')).toBe(false);
      fireEvent.click(screen.getByRole('button', { name: /Generating the final response/ }));
      expect(container.querySelector('.trace-layout')?.classList.contains('show-detail')).toBe(true);
      expect(screen.getByText('<img src=x onerror=alert(1)>')).toBeTruthy();
      expect(container.querySelector('img')).toBeNull();
      fireEvent.click(screen.getByRole('button', { name: 'Copy trace' }));
      expect(await screen.findByText('Trace copied')).toBeTruthy();
      expect(JSON.parse(copied)).toMatchObject({ request_id: 'r', turn_id: 't', simulated: false });
      expect(copied).not.toContain('private operator query');
      expect(screen.getByText('0')).toBeTruthy();
      expect(screen.getByText('Unavailable')).toBeTruthy();
    } finally {
      vi.unstubAllGlobals();
    }
  });
  it('validates bounded trace events and rejects arbitrary native fields', () => {
    expect(eventSchema.safeParse({ ...envelope, type: 'trace.step', step }).success).toBe(true);
    expect(
      eventSchema.safeParse({ ...envelope, type: 'trace.step', step: { ...step, native: { secret: 'hidden' } } })
        .success,
    ).toBe(false);
    expect(
      eventSchema.safeParse({ ...envelope, type: 'trace.step', step: { ...step, response: 'x'.repeat(16_385) } })
        .success,
    ).toBe(false);
  });

  it('upserts a step on its original turn and retains failure details when a later turn starts', async () => {
    const client = new DemoClient();
    client.diagnose = async (_input, receive) => {
      receive(
        eventSchema.parse({
          ...envelope,
          type: 'trace.started',
          provider: 'ollama',
          model: 'qwen',
          started_at: step.started_at,
        }),
      );
      receive(eventSchema.parse({ ...envelope, type: 'trace.step', step }));
      receive(
        eventSchema.parse({
          ...envelope,
          type: 'trace.step',
          step: {
            ...step,
            state: 'failed',
            duration_ms: 800,
            finished_at: '2026-10-28T09:00:00.800Z',
            code: 'provider_timeout',
          },
        }),
      );
      receive({ ...envelope, type: 'turn.failed', code: 'provider_timeout', message: 'Model provider timed out' });
    };
    const { result } = renderHook(() => useInvestigation(client, 'local'));
    await act(() => result.current.run('Inspect'));
    expect(result.current.turns[0]).toMatchObject({
      state: 'failed',
      serverTurnId: 'turn-1',
      trace: { provider: 'ollama', model: 'qwen', steps: [{ id: 'step-1', state: 'failed', duration_ms: 800 }] },
    });
    client.diagnose = async (_input, receive) => receive({ ...envelope, turn_id: 'turn-2', type: 'turn.completed' });
    await act(() => result.current.run('New question'));
    expect(result.current.turns[0]?.trace?.steps).toHaveLength(1);
    expect(result.current.turns[1]?.trace).toBeUndefined();
  });
});
