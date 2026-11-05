import { useEffect, useRef, useState } from 'react';
import { ApiError } from './api';
import { targetKey, type Answer, type DiagnosticTarget, type Transport } from './contracts';
import type { ModelSelection } from './model-contracts';
import type { InvestigationDetail, SavedTurn, StartTurn, TurnPage } from './investigation-contracts';
import type { Turn } from './useInvestigation';

export interface SavedContext {
  draft?: string;
  restoreDraft?: (value: string) => Promise<void>;
  enabled?: boolean;
  detail?: InvestigationDetail;
  flush: () => Promise<boolean>;
  revision: () => number;
  refresh: () => Promise<void>;
  changed: () => void;
  conflict?: (current: unknown) => void;
}

/** Render persisted attempts as questions and recover observation without resubmitting work. */
export function useSavedTurns(client: Transport, host: string, selection?: ModelSelection, saved?: SavedContext) {
  const history = client.history;
  const [snapshots, setSnapshots] = useState<TurnPage['items']>(saved?.detail?.turns.items ?? []);
  const [nextCursor, setNextCursor] = useState(saved?.detail?.turns.next_cursor ?? null);
  const [error, setError] = useState('');
  const [errorSource, setErrorSource] = useState<'server' | 'client'>('client');
  const [observing, setObserving] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [olderLoading, setOlderLoading] = useState(false);
  const active = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const latest = useRef(saved);
  useEffect(() => {
    latest.current = saved;
  }, [saved]);
  const runningId = useRef(saved?.detail?.active_turn_id ?? null);
  const submittingRef = useRef(false);
  const id = saved?.detail?.id;

  useEffect(() => {
    const incoming = saved?.detail?.turns.items;
    if (!incoming) return;
    let attached = true;
    queueMicrotask(() => {
      if (!attached) return;
      setSnapshots((previous) => {
        const byId = new Map(previous.map((row) => [row.id, row]));
        let changed = false;
        for (const row of incoming) {
          const old = byId.get(row.id);
          if (
            !old ||
            (!('revision' in old) && 'revision' in row) ||
            ('revision' in old && 'revision' in row && row.revision > old.revision)
          ) {
            byId.set(row.id, row);
            changed = true;
          }
        }
        return changed ? [...byId.values()] : previous;
      });
    });
    return () => {
      attached = false;
    };
  }, [saved?.detail?.turns.items]);

  /** Reject another host/chat and stale revisions before exposing a committed snapshot. */
  function receive(snapshot: SavedTurn) {
    if (snapshot.investigation_id !== id || snapshot.host !== host)
      throw new Error('Turn response is outside the selected scope.');
    runningId.current = snapshot.state === 'running' ? snapshot.id : null;
    setSnapshots((previous) => {
      const existing = previous.find((row) => row.id === snapshot.id);
      if (existing && 'revision' in existing && existing.revision >= snapshot.revision) return previous;
      return existing ? previous.map((row) => (row.id === snapshot.id ? snapshot : row)) : [...previous, snapshot];
    });
  }

  /** Read and observe the same turn with bounded backoff while visible and online. */
  async function observe(turnId: string, controller: AbortController, epoch: number) {
    if (!history) return;
    let failures = 0;
    while (!controller.signal.aborted && generation.current === epoch) {
      try {
        await available(controller.signal);
        const current = await history.turn(turnId, controller.signal);
        if (controller.signal.aborted || generation.current !== epoch) return;
        receive(current);
        setError('');
        if (current.state !== 'running') {
          latest.current?.changed();
          return;
        }
        setObserving(true);
        await history.observeTurn(
          turnId,
          (snapshot) => {
            if (!controller.signal.aborted && generation.current === epoch) receive(snapshot);
          },
          controller.signal,
        );
        if (!runningId.current) {
          latest.current?.changed();
          return;
        }
      } catch (failure) {
        if (controller.signal.aborted || generation.current !== epoch) return;
        setObserving(false);
        setErrorSource('client');
        if (failure instanceof ApiError && [401, 403, 404].includes(failure.httpStatus ?? 0)) {
          setError(
            failure.httpStatus === 404
              ? 'This saved turn is unavailable.'
              : 'Sign in again to observe this saved turn.',
          );
          return;
        }
        setError('Observation disconnected. Reconnecting to the saved turn.');
      }
      try {
        await delay([1000, 2000, 4000, 8000, 10_000][Math.min(failures++, 4)]!, controller.signal);
      } catch {
        return;
      }
    }
  }

  useEffect(() => {
    if (!history || !id || saved?.enabled === false) return;
    const controller = new AbortController();
    active.current = controller;
    const epoch = ++generation.current;
    const running = latest.current?.detail?.active_turn_id;
    if (running) void observe(running, controller, epoch);
    return () => {
      generation.current = epoch + 1;
      controller.abort();
      active.current?.abort();
    };
    // The enclosing workspace remounts for each account, host and chat selection.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [history, id, host, saved?.enabled]);

  /** Admit a question or exact saved clarification once, recovering a lost response through reads. */
  async function submit(input: Omit<StartTurn, 'expected_revision'>, preservedDraft?: string) {
    if (!history || !id || !saved || submittingRef.current || runningId.current) return;
    submittingRef.current = true;
    setSubmitting(true);
    setError('');
    setErrorSource('client');
    const epoch = generation.current;
    try {
      if (!(await saved.flush()) || generation.current !== epoch) return;
      active.current?.abort();
      const controller = new AbortController();
      active.current = controller;
      const target = input.target;
      if (target?.kind === 'container') await client.container(host, target.id, controller.signal);
      let snapshot: SavedTurn;
      try {
        snapshot = (
          await history.startTurn(id, { ...input, expected_revision: saved.revision() } as StartTurn, controller.signal)
        ).snapshot;
      } catch (failure) {
        if (controller.signal.aborted || generation.current !== epoch) return;
        if (failure instanceof ApiError) throw failure;
        const recovered = await history.investigation(id, controller.signal);
        const receipt = recovered.turns.items.find(
          (row): row is SavedTurn => 'submission_id' in row && row.submission_id === input.submission_id,
        );
        if (!receipt) throw failure;
        snapshot = receipt;
      }
      if (controller.signal.aborted || generation.current !== epoch) return;
      receive(snapshot);
      await saved.refresh();
      if (generation.current !== epoch) return;
      if (preservedDraft) await saved.restoreDraft?.(preservedDraft);
      saved.changed();
      if (snapshot.state === 'running') void observe(snapshot.id, controller, epoch);
    } catch (failure) {
      if (generation.current !== epoch) return;
      setErrorSource(failure instanceof ApiError ? 'server' : 'client');
      if (failure instanceof ApiError && failure.code === 'workspace_conflict') saved.conflict?.(failure.current);
      setError(
        failure instanceof ApiError
          ? failure.message
          : 'Could not submit the question. Check saved history before trying again.',
      );
    } finally {
      if (generation.current === epoch) {
        submittingRef.current = false;
        setSubmitting(false);
      }
    }
  }

  /** Start a new explicit question with fresh Docker evidence. */
  async function run(query: string, fresh = false, target?: DiagnosticTarget) {
    if (!query.trim() || query.trim().length > 4000) return;
    await submit(
      {
        kind: 'question',
        query: query.trim(),
        target: target ?? null,
        model: selection ?? null,
        submission_id: crypto.randomUUID(),
      } as StartTurn,
      fresh ? saved?.draft : undefined,
    );
  }

  /** Continue the saved original question with the parent revision and exact observed candidate. */
  async function chooseTarget(turnId: string, target: DiagnosticTarget) {
    const row = snapshots.find((snapshot): snapshot is SavedTurn => 'state' in snapshot && snapshot.id === turnId);
    const candidate = row?.selection?.candidates.find((value) => targetKey(value) === targetKey(target));
    if (!row || row.state !== 'awaiting_selection' || row.resolved_by_turn_id || !candidate) return;
    await submit({
      kind: 'clarification',
      clarification_of: row.id,
      expected_parent_revision: row.revision,
      target: candidate,
      model: selection ?? null,
      submission_id: crypto.randomUUID(),
    } as StartTurn);
  }

  /** Stop explicitly, retaining the authoritative terminal state returned by the server. */
  async function stop() {
    if (!history || !runningId.current) return;
    const epoch = generation.current;
    try {
      const result = await history.cancelTurn(runningId.current);
      if (generation.current === epoch) {
        receive(result);
        active.current?.abort();
        saved?.changed();
      }
    } catch {
      if (generation.current === epoch) setError('Could not stop the diagnosis. Check the saved turn.');
    }
  }

  /** Load older answer snapshots independently of the model's limited context. */
  async function older() {
    if (!history || !id || !nextCursor || olderLoading) return;
    const epoch = generation.current;
    setOlderLoading(true);
    try {
      const page = await history.olderTurns(id, nextCursor, new AbortController().signal);
      if (generation.current !== epoch) return;
      setSnapshots((previous) => [
        ...page.items,
        ...previous.filter((row) => !page.items.some((old) => old.id === row.id)),
      ]);
      setNextCursor(page.next_cursor);
    } catch {
      if (generation.current === epoch) setError('Could not load older answers.');
    } finally {
      if (generation.current === epoch) setOlderLoading(false);
    }
  }

  return {
    turns: project(snapshots),
    running: submitting || snapshots.some((row) => 'state' in row && row.state === 'running'),
    run,
    chooseTarget,
    stop,
    clear: () => {
      active.current?.abort();
      generation.current++;
      setSnapshots([]);
    },
    example: (_answer: Answer, _query: string) => {
      void _answer;
      void _query;
    },
    error,
    errorSource,
    observing,
    older,
    nextCursor,
    olderLoading,
  };
}

/** Group clarification attempts under one original question without discarding attempt metadata. */
function project(snapshots: TurnPage['items']): Turn[] {
  const groups = new Map<string, Turn>();
  for (const row of snapshots) {
    if (!('state' in row)) {
      groups.set(row.id, {
        id: row.id,
        query: 'Unsupported saved answer',
        exampleQuery: true,
        state: 'failed',
        progress: [],
        error: 'This saved answer uses an unsupported schema.',
        errorSource: 'client',
        code: 'history_unsupported',
      });
      continue;
    }
    const root = row.clarification_of
      ? ([...groups.entries()].find(([, turn]) =>
          turn.attempts?.some((attempt) => attempt.id === row.clarification_of),
        )?.[0] ?? row.clarification_of)
      : row.id;
    const previous = groups.get(root);
    groups.set(root, {
      id: row.id,
      query: previous?.query ?? row.query,
      target: row.target ?? undefined,
      state: row.state,
      progress: row.progress.map((item) => ({ ...item, state: item.state === 'succeeded' ? 'done' : item.state })),
      answer: row.answer ?? undefined,
      selection: row.selection ?? undefined,
      error: row.error?.message,
      errorSource: 'server',
      code: row.error?.code,
      requestId: row.request_id,
      serverTurnId: row.id,
      trace: {
        provider: row.model?.provider ?? null,
        model: row.model?.model ?? null,
        started_at: row.created_at,
        steps: row.trace,
      },
      createdAt: previous?.createdAt ?? row.created_at,
      updatedAt: row.updated_at,
      attempts: [...(previous?.attempts ?? []), row],
    });
  }
  return [...groups.values()];
}

/** Wait for visibility and connectivity without polling or admitting new work. */
async function available(signal: AbortSignal): Promise<void> {
  if (navigator.onLine && document.visibilityState !== 'hidden') return;
  await new Promise<void>((resolve, reject) => {
    const finish = () => {
      window.removeEventListener('online', check);
      document.removeEventListener('visibilitychange', check);
      signal.removeEventListener('abort', abort);
    };
    const check = () => {
      if (navigator.onLine && document.visibilityState !== 'hidden') {
        finish();
        resolve();
      }
    };
    const abort = () => {
      finish();
      reject(signal.reason);
    };
    window.addEventListener('online', check);
    document.addEventListener('visibilitychange', check);
    signal.addEventListener('abort', abort, { once: true });
    if (signal.aborted) abort();
  });
}

/** Bound an observation retry delay and release it promptly on detach. */
async function delay(milliseconds: number, signal: AbortSignal) {
  await new Promise<void>((resolve, reject) => {
    const abort = () => {
      clearTimeout(timer);
      reject(signal.reason);
    };
    const timer = setTimeout(() => {
      signal.removeEventListener('abort', abort);
      resolve();
    }, milliseconds);
    signal.addEventListener('abort', abort, { once: true });
    if (signal.aborted) abort();
  });
}
