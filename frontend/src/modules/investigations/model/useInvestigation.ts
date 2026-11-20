import { useEffect, useRef, useState } from 'react';
import { ApiError } from '../../../shared/contracts/errors';
import { targetKey } from '../../../shared/contracts/contracts';
import type { Answer, DiagnosticTarget, TurnEvent } from '../../../shared/contracts/contracts';
import type { Transport } from '../../../shared/contracts/transport';
import type { ModelSelection } from '../../../shared/contracts/model-contracts';
import { useSavedTurns, type SavedContext } from './useSavedTurns';
import type { Turn } from './turns';

interface DemoWorkspace {
  draft: string;
  scenario: string;
}

interface DemoChat {
  id: string;
  turns: Turn[];
  workspace: DemoWorkspace;
  session?: string;
  scope?: DiagnosticTarget;
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
    ? { ...durable, demoChats: undefined }
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
  const [chatId, setChatId] = useState<string>(() => crypto.randomUUID());
  const [archives, setArchives] = useState<DemoChat[]>([]);
  const active = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const scope = useRef<DiagnosticTarget | undefined>(undefined);
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
    scope.current = undefined;
    setTurns([]);
  }

  /** Retain the previous Demo workspace before opening another in this tab. */
  function switchChat(workspace: DemoWorkspace, next?: DemoChat) {
    const old = { id: chatId, turns, workspace, session: session.current, scope: scope.current };
    setArchives((previous) => {
      const retained = previous.filter((chat) => chat.id !== next?.id);
      return old.turns.length || old.workspace.draft ? [old, ...retained] : retained;
    });
    setChatId(next?.id ?? crypto.randomUUID());
    setTurns(next?.turns ?? []);
    session.current = next?.session;
    scope.current = next?.scope;
  }

  /** Open a previously retained Demo workspace without submitting a turn. */
  function openChat(id: string, workspace: DemoWorkspace) {
    if (active.current) return;
    const next = archives.find((chat) => chat.id === id);
    if (!next) return;
    switchChat(workspace, next);
    return next.workspace;
  }

  /** Start another Demo workspace only when the active stream has settled. */
  function newChat(workspace: DemoWorkspace) {
    if (active.current) return false;
    switchChat(workspace);
    return true;
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
          case 'turn.started':
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
    const containerScope = !freshSession && scope.current?.kind === 'container' ? scope.current : undefined;
    return requestTurn({ id: crypto.randomUUID(), query, target: target ?? containerScope }, freshSession);
  }

  /** Let an explicit continuation carry the current Demo session to another target. */
  function diagnoseContainer(query: string, target: DiagnosticTarget) {
    if (active.current) return;
    scope.current = target;
    return run(query, false, target);
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
    if (freshSession || (!continuing && transientScope(target) !== transientScope(scope.current)))
      session.current = undefined;
    if (!continuing) scope.current = target;
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
        diagnosticInput(host, query, target, session.current, selection),
        (event) => {
          if (generation.current === current) receive(id, event);
        },
        controller.signal,
      );
    } catch (error) {
      if (generation.current !== current) return;
      const code = error instanceof ApiError ? error.code : 'connection_error';
      if (['session_not_found', 'session_expired'].includes(code)) session.current = undefined;
      setTurns((previous) => previous.map((turn) => failedTransientTurn(turn, id, code, error)));
    } finally {
      if (generation.current === current) active.current = null;
    }
  }

  return {
    turns,
    lastTarget: turns.filter((turn) => turn.target).at(-1)?.target,
    running,
    run,
    chooseTarget,
    stop,
    clear,
    example,
    demoChats: { archives, newChat, openChat, diagnoseContainer },
  };
}

/** Identify the transient session scope without matching resources by display name. */
function transientScope(target: DiagnosticTarget | undefined): string {
  return target ? targetKey(target) : '';
}

/** Build the same scoped request for one transient diagnosis attempt. */
function diagnosticInput(
  host: string,
  query: string,
  target: DiagnosticTarget | undefined,
  session: string | undefined,
  selection: ModelSelection | undefined,
): Parameters<Transport['diagnose']>[0] {
  return {
    host,
    query,
    ...(target?.kind === 'container' ? { container_id: target.id } : target ? { group: target } : {}),
    ...(session ? { session_id: session } : {}),
    ...(selection ? { model_selection: selection } : {}),
  };
}

/** Keep transport failure details on the attempt that owns them. */
function failedTransientTurn(turn: Turn, id: string, code: string, error: unknown): Turn {
  return turn.id === id
    ? {
        ...turn,
        state: 'failed',
        code,
        error: error instanceof Error ? error.message : 'Connection failed. Retry manually.',
        errorSource: error instanceof ApiError ? error.source : 'client',
      }
    : turn;
}
