import { useEffect, useRef, useState } from 'react';
import { ApiError } from './api';
import { targetKey } from './contracts';
import type { Answer, DiagnosticTarget, TargetSelection, TraceStep, Transport, TurnEvent } from './contracts';
import type { ModelSelection } from './model-contracts';
import type { SavedTurn } from './investigation-contracts';
import { useSavedTurns, type SavedContext } from './useSavedTurns';

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
  target?: DiagnosticTarget;
  exampleQuery?: true;
  state: 'running' | 'completed' | 'failed' | 'stopped' | 'awaiting_selection' | 'interrupted';
  progress: ToolProgress[];
  answer?: Answer;
  selection?: TargetSelection;
  error?: string;
  errorSource?: 'server' | 'client';
  code?: string;
  requestId?: string;
  serverTurnId?: string;
  trace?: TurnTrace;
  createdAt?: string;
  updatedAt?: string;
  attempts?: SavedTurn[];
}

/** Select durable API recovery or explicitly ephemeral simulated turns by transport capability. */
export function useInvestigation(
  client: Transport,
  host: string,
  initial?: Answer,
  selection?: ModelSelection,
  saved?: SavedContext,
) {
  const durable = useSavedTurns(client, host, selection, saved);
  const transient = useTransientInvestigation(client, host, initial, selection);
  return client.history
    ? durable
    : {
        ...transient,
        error: '',
        errorSource: 'client' as const,
        observing: false,
        older: async () => {},
        nextCursor: null,
        olderLoading: false,
      };
}

/** Manage ephemeral turns and protect the workspace from late events after cancellation. */
function useTransientInvestigation(client: Transport, host: string, initial?: Answer, selection?: ModelSelection) {
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
    generation.current++;
    active.current?.abort();
    active.current = null;
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

  /** Add a new operator question or explicit manual retry to this tab's history. */
  function run(query: string, freshSession = false, target?: DiagnosticTarget) {
    return requestTurn({ id: crypto.randomUUID(), query, target }, freshSession);
  }

  /** Continue an unresolved question with a server-observed identity, preserving this host's conversation. */
  async function chooseTarget(id: string, target: DiagnosticTarget) {
    const turn = turns.find((row) => row.id === id && row.state === 'awaiting_selection');
    const observed = turn?.selection?.candidates.find((row) => targetKey(row) === targetKey(target));
    if (!turn || !observed) return;
    await requestTurn({ id, query: turn.query, target: observed }, false, true);
  }

  /** Run one transport attempt, replacing a pending choice without mixing its old events or trace into the diagnosis. */
  async function requestTurn(input: Pick<Turn, 'id' | 'query' | 'target'>, freshSession = false, continuing = false) {
    const { id, target } = input;
    const query = input.query.trim();
    if (active.current || !query || !host) return;
    const nextScope = target ? targetKey(target) : '';
    if (freshSession || (!continuing && nextScope !== scope.current)) session.current = undefined;
    if (!continuing) scope.current = nextScope;
    const controller = new AbortController();
    active.current = controller;
    const current = ++generation.current;
    const next: Turn = { id, query, target, state: 'running', progress: [] };
    setTurns((previous) =>
      previous.some((turn) => turn.id === id)
        ? previous.map((turn) => (turn.id === id ? next : turn))
        : [...previous, next],
    );
    try {
      await client.diagnose(
        {
          host,
          query,
          ...(target?.kind === 'container' ? { container_id: target.id } : target ? { group: target } : {}),
          ...(session.current ? { session_id: session.current } : {}),
          ...(selection ? { model_selection: selection } : {}),
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

  return { turns, running, run, chooseTarget, stop, clear, example };
}
