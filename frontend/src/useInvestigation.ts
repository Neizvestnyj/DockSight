import { useEffect, useRef, useState } from 'react';
import { ApiError } from './api';
import type { Answer, GroupSelection, GroupTarget, TraceStep, Transport, TurnEvent } from './contracts';

export interface TurnTrace {
  provider: string | null;
  model: string | null;
  started_at: string | null;
  steps: TraceStep[];
}

export interface ToolProgress {
  tool: string;
  state: 'running' | 'done' | 'failed';
}
export interface Turn {
  id: string;
  query: string;
  group?: GroupTarget;
  exampleQuery?: true;
  state: 'running' | 'completed' | 'failed' | 'stopped' | 'awaiting_selection';
  progress: ToolProgress[];
  answer?: Answer;
  selection?: GroupSelection;
  error?: string;
  errorSource?: 'server' | 'client';
  code?: string;
  requestId?: string;
  serverTurnId?: string;
  trace?: TurnTrace;
}

/** Manage ephemeral turns and protect the workspace from late events after cancellation. */
export function useInvestigation(client: Transport, host: string, initial?: Answer) {
  const [turns, setTurns] = useState<Turn[]>(() =>
    initial
      ? [
          {
            id: 'example',
            query: 'Why does payments-api keep restarting?',
            exampleQuery: true,
            state: 'completed',
            progress: [],
            answer: initial,
          },
        ]
      : [],
  );
  const session = useRef<string | undefined>(undefined);
  const active = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const scope = useRef('');
  const running = turns.some((turn) => turn.state === 'running');

  useEffect(
    () => () => {
      active.current?.abort();
    },
    [],
  );

  /** End the current lease locally; the backend cancels diagnostic work on disconnect. */
  function stop() {
    generation.current++;
    active.current?.abort();
    active.current = null;
    setTurns((previous) => previous.map((turn) => (turn.state === 'running' ? { ...turn, state: 'stopped' } : turn)));
  }

  /** Begin a separate session without claiming a durable history exists. */
  function clear() {
    stop();
    session.current = undefined;
    setTurns([]);
  }

  /** Render a retained demo investigation without pretending it came from a live backend. */
  function example(answer: Answer, query: string) {
    clear();
    setTurns([{ id: crypto.randomUUID(), query, exampleQuery: true, state: 'completed', progress: [], answer }]);
  }

  /** Apply an ordered event to its own turn rather than to a global latest answer. */
  function receive(id: string, event: TurnEvent) {
    if (event.type === 'turn.started') session.current = event.session_id;
    setTurns((previous) =>
      previous.map((turn) => {
        if (turn.id !== id) return turn;
        const common = { ...turn, requestId: event.request_id, serverTurnId: event.turn_id ?? turn.serverTurnId };
        switch (event.type) {
          case 'trace.started':
            return {
              ...common,
              trace: {
                provider: event.provider,
                model: event.model,
                started_at: event.started_at,
                steps: turn.trace?.steps ?? [],
              },
            };
          case 'trace.step': {
            const trace = turn.trace ?? { provider: null, model: null, started_at: null, steps: [] };
            const existing = trace.steps.some((row) => row.id === event.step.id);
            const steps = existing
              ? trace.steps.map((row) => (row.id === event.step.id ? event.step : row))
              : [...trace.steps, event.step].slice(0, 133);
            return { ...common, trace: { ...trace, steps } };
          }
          case 'tool.started':
            return { ...common, progress: [...turn.progress, { tool: event.tool, state: 'running' }] };
          case 'tool.completed': {
            const index = turn.progress.findIndex((row) => row.tool === event.tool && row.state === 'running');
            return {
              ...common,
              progress: turn.progress.map((row, i) =>
                i === index ? { ...row, state: event.ok ? 'done' : 'failed' } : row,
              ),
            };
          }
          case 'answer.ready':
            return { ...common, answer: event.answer };
          case 'clarification.required':
            return { ...common, selection: event.selection };
          case 'turn.completed':
            return { ...common, state: turn.selection ? 'awaiting_selection' : 'completed' };
          case 'turn.failed':
            return { ...common, state: 'failed', error: event.message, errorSource: 'server', code: event.code };
          default:
            return common;
        }
      }),
    );
    if (event.type === 'turn.failed' && ['session_not_found', 'session_expired'].includes(event.code))
      session.current = undefined;
  }

  /** Start exactly one manual request; retries are explicit operator submissions. */
  async function run(query: string, freshSession = false, group?: GroupTarget) {
    if (active.current || !query.trim() || !host) return;
    const nextScope = group ? `${group.kind}:${group.name}` : '';
    if (freshSession || nextScope !== scope.current) session.current = undefined;
    scope.current = nextScope;
    const controller = new AbortController();
    active.current = controller;
    const current = ++generation.current;
    const id = crypto.randomUUID();
    setTurns((previous) => [...previous, { id, query: query.trim(), group, state: 'running', progress: [] }]);
    try {
      await client.diagnose(
        {
          host,
          query: query.trim(),
          ...(group ? { group } : {}),
          ...(session.current ? { session_id: session.current } : {}),
        },
        (event) => {
          if (generation.current === current) receive(id, event);
        },
        controller.signal,
      );
    } catch (error) {
      if (generation.current !== current) return;
      const code = error instanceof ApiError ? error.code : 'connection_error';
      if (['session_not_found', 'session_expired'].includes(code)) session.current = undefined;
      setTurns((previous) =>
        previous.map((turn) =>
          turn.id === id
            ? {
                ...turn,
                state: 'failed',
                code,
                error: error instanceof Error ? error.message : 'Connection failed. Retry manually.',
                errorSource: error instanceof ApiError ? error.source : 'client',
              }
            : turn,
        ),
      );
    } finally {
      if (generation.current === current) active.current = null;
    }
  }

  return { turns, running, run, stop, clear, example };
}
