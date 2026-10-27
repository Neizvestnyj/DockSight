import { useEffect, useRef, useState } from 'react';
import { ApiError } from './api';
import type { Answer, Transport, TurnEvent } from './contracts';

export interface ToolProgress {
  tool: string;
  state: 'running' | 'done' | 'failed';
}
export interface Turn {
  id: string;
  query: string;
  exampleQuery?: true;
  state: 'running' | 'completed' | 'failed' | 'stopped';
  progress: ToolProgress[];
  answer?: Answer;
  error?: string;
  errorSource?: 'server' | 'client';
  code?: string;
  requestId?: string;
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
        const common = { ...turn, requestId: event.request_id };
        switch (event.type) {
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
          case 'turn.completed':
            return { ...common, state: 'completed' };
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
  async function run(query: string, freshSession = false) {
    if (active.current || !query.trim() || !host) return;
    if (freshSession) session.current = undefined;
    const controller = new AbortController();
    active.current = controller;
    const current = ++generation.current;
    const id = crypto.randomUUID();
    setTurns((previous) => [...previous, { id, query: query.trim(), state: 'running', progress: [] }]);
    try {
      await client.diagnose(
        { host, query: query.trim(), ...(session.current ? { session_id: session.current } : {}) },
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
