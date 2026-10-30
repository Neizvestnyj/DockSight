import type { TraceStep, TurnEvent } from './contracts';
import type { ModelSelection } from './model-contracts';

/** Measure simulated transport delays while emitting the same owned trace contract as the backend. */
export function demoTrace(
  envelope: { schema_version: 1; request_id: string; turn_id: string },
  receive: (event: TurnEvent) => void,
  selection?: ModelSelection,
) {
  let sequence = 0;
  receive({
    ...envelope,
    type: 'trace.started',
    provider: selection?.provider ?? 'ollama',
    model: selection?.model ?? 'qwen3.5:9b',
    started_at: new Date().toISOString(),
  });
  return (kind: TraceStep['kind'], operation: string) => {
    const started = performance.now();
    const step: TraceStep = {
      id: `step-${++sequence}`,
      kind,
      operation,
      state: 'running',
      started_at: new Date().toISOString(),
      finished_at: null,
      duration_ms: null,
      input_tokens: null,
      output_tokens: null,
      code: null,
      issues: [],
      response: null,
      response_truncated: false,
    };
    receive({ ...envelope, type: 'trace.step', step });
    return (extra: Partial<Pick<TraceStep, 'code' | 'response'>> = {}) =>
      receive({
        ...envelope,
        type: 'trace.step',
        step: {
          ...step,
          ...extra,
          state: extra.code ? 'failed' : 'succeeded',
          finished_at: new Date().toISOString(),
          duration_ms: Math.max(0, Math.round(performance.now() - started)),
        },
      });
  };
}
