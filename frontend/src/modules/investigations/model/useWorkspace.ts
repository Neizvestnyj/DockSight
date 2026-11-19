import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '../../../shared/contracts/errors';
import {
  actorWorkspaceSchema,
  type ActorChanges,
  type ActorWorkspace,
  type HistoryTransport,
  type InvestigationDetail,
  type InvestigationWorkspace,
  type WorkspaceChanges,
} from '../../../shared/contracts/investigation-contracts';

import { useWorkspaceWrites, type InitialCreation, type InitialDraft, type SaveState } from './workspace-writes';

/** Keep acknowledged server revisions separate from unsent text and serialize local writes. */
export function useWorkspace(history?: HistoryTransport) {
  const [ready, setReady] = useState(!history);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [actor, setActor] = useState<ActorWorkspace>();
  const [detail, setDetail] = useState<InvestigationDetail>();
  const [draft, showDraft] = useState('');
  const [saveState, setSaveState] = useState<SaveState>('saved');
  const [attempt, setAttempt] = useState(0);
  const current = useRef<InvestigationDetail | undefined>(undefined);
  const principal = useRef<ActorWorkspace | undefined>(undefined);
  const pending = useRef<WorkspaceChanges>({});
  const actorPending = useRef<ActorChanges>({});
  const writing = useRef<Promise<boolean> | null>(null);
  const actorWriting = useRef<Promise<boolean> | null>(null);
  const conflict = useRef<InvestigationWorkspace | null>(null);
  const generation = useRef(0);
  const accountGeneration = useRef(0);
  const active = useRef<AbortController | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const initialDraft = useRef<InitialDraft | null>(null);
  const initialCreation = useRef<InitialCreation | null>(null);
  const historyOwner = useRef(history);
  const clearPendingSave = useCallback(() => clearTimeout(timer.current), []);

  /** Install only a server-acknowledged workspace for the selected chat. */
  const install = useCallback((value: InvestigationDetail) => {
    current.current = value;
    pending.current = {};
    conflict.current = null;
    setDetail(value);
    showDraft(value.workspace.draft);
    setSaveState('saved');
  }, []);

  /** Save queued preference changes in order without letting another tab navigate this one. */
  async function savePreferences(changes: ActorChanges): Promise<boolean> {
    if (!history || !principal.current) return false;
    Object.assign(actorPending.current, changes);
    if (actorWriting.current) return actorWriting.current;
    const epoch = accountGeneration.current;
    const operation = (async () => {
      while (Object.keys(actorPending.current).length && principal.current) {
        const patch = actorPending.current;
        actorPending.current = {};
        try {
          const result = await history.saveActorWorkspace(principal.current.revision, patch);
          if (accountGeneration.current !== epoch) return false;
          principal.current = result;
          setActor(result);
        } catch (failure) {
          if (accountGeneration.current !== epoch) return false;
          if (failure instanceof ApiError && failure.code === 'workspace_conflict') {
            const parsed = actorWorkspaceSchema.safeParse(failure.current);
            if (parsed.success) {
              principal.current = parsed.data;
              setActor(parsed.data);
            }
          }
          setError('Workspace preferences could not be saved. Choose the preference again to retry.');
          return false;
        }
      }
      return true;
    })();
    actorWriting.current = operation;
    try {
      return await operation;
    } finally {
      if (actorWriting.current === operation) actorWriting.current = null;
    }
  }

  const { flush, patch, reloadConflict, useDraft, conflictWith, restoreDraft } = useWorkspaceWrites({
    history,
    current,
    pending,
    writing,
    conflict,
    generation,
    timer,
    initialDraft,
    initialCreation,
    draft,
    showDraft,
    setSaveState,
    setDetail,
    install,
  });

  /** Reject replies after their workspace generation was detached. */
  function detached(epoch: number, signal: AbortSignal): boolean {
    return generation.current !== epoch || signal.aborted;
  }

  /** Preserve newer acknowledged workspace data already installed for the same chat. */
  function currentWorkspace(id: string, result: InvestigationDetail) {
    const acknowledged = current.current?.id === id ? current.current.workspace : result.workspace;
    return acknowledged.revision > result.workspace.revision ? acknowledged : result.workspace;
  }

  /** Drop a provisional draft when a different initial creation owns its scope. */
  function prepareInitialDraft(initial: boolean, host: string) {
    if (
      initial &&
      initialDraft.current &&
      (initialCreation.current || (initialDraft.current.host && initialDraft.current.host !== host))
    ) {
      initialDraft.current = null;
      showDraft('');
      setSaveState('saved');
    }
  }

  /** Transfer a matching provisional draft only after its initial chat was acknowledged. */
  function takeInitialDraft(initial: boolean, epoch: number): string | undefined {
    const retained = initial && initialDraft.current?.epoch === epoch ? initialDraft.current.value : undefined;
    if (initial) {
      initialDraft.current = null;
      initialCreation.current = null;
    }
    return retained;
  }

  /** Leave a failed initial draft visible without claiming it was saved. */
  function failInitialCreation(initial: boolean, epoch: number) {
    if (initial && initialCreation.current?.epoch === epoch) {
      initialCreation.current = null;
      if (initialDraft.current?.epoch === epoch) initialDraft.current = { ...initialDraft.current, epoch: null };
    }
  }

  /** Merge a refresh without rebasing dirty draft state or another workspace's revision. */
  function mergeRefresh(result: InvestigationDetail, id: string, epoch: number): boolean {
    if (generation.current !== epoch || current.current?.id !== id) return false;
    const acknowledged = current.current.workspace;
    const dirty = Boolean(Object.keys(pending.current).length || conflict.current);
    if (dirty && result.workspace.revision > acknowledged.revision) {
      if (!conflict.current || result.workspace.revision >= conflict.current.revision)
        conflict.current = result.workspace;
      clearTimeout(timer.current);
      setSaveState('conflict');
    }
    current.current = {
      ...result,
      workspace: dirty || result.workspace.revision < acknowledged.revision ? acknowledged : result.workspace,
    };
    setDetail(current.current);
    if (!Object.keys(pending.current).length && !writing.current && !conflict.current)
      showDraft(current.current.workspace.draft);
    return true;
  }

  /** Detach old reads before opening another owned archive. */
  async function open(id: string) {
    if (!history) return;
    if (!(await flush())) return;
    const openingInitial = !current.current;
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    const epoch = ++generation.current;
    setLoading(true);
    setError('');
    try {
      const result = await history.investigation(id, controller.signal);
      if (detached(epoch, controller.signal)) return;
      if (!(await flush()) || detached(epoch, controller.signal)) return;
      const workspace = currentWorkspace(id, result);
      if (openingInitial) {
        initialDraft.current = null;
        initialCreation.current = null;
      }
      install({
        ...result,
        workspace,
      });
      await savePreferences({ last_investigation_id: id });
    } catch {
      if (!detached(epoch, controller.signal)) {
        if (openingInitial && !current.current) {
          initialCreation.current = null;
          if (initialDraft.current) initialDraft.current = { ...initialDraft.current, epoch: null };
        }
        setError('Could not open saved chat. Retry the read.');
      }
    } finally {
      if (generation.current === epoch) setLoading(false);
    }
  }

  /** Create one explicit chat without deleting any previous archive. */
  async function create(host: string) {
    if (!history || !host) return;
    if (!(await flush())) return;
    active.current?.abort();
    const initial = !current.current;
    prepareInitialDraft(initial, host);
    const epoch = ++generation.current;
    if (initial) {
      initialCreation.current = { host, epoch };
      if (initialDraft.current) initialDraft.current = { ...initialDraft.current, host, epoch };
    }
    clearTimeout(timer.current);
    setLoading(true);
    setError('');
    try {
      const result = await history.createInvestigation(crypto.randomUUID(), host);
      if (generation.current !== epoch) return;
      if (!(await flush()) || generation.current !== epoch) return;
      const retained = takeInitialDraft(initial, epoch);
      install({ ...result, turns: { items: [], next_cursor: null } });
      if (retained !== undefined) patch({ draft: retained });
      await savePreferences({ last_investigation_id: result.id, host });
    } catch {
      if (generation.current === epoch) {
        failInitialCreation(initial, epoch);
        setError('Could not create saved chat. Retry manually.');
      }
    } finally {
      if (generation.current === epoch) setLoading(false);
    }
  }

  /** Refresh metadata after acceptance while preserving any newly typed local draft. */
  const refresh = useCallback(async () => {
    if (!history || !current.current) return;
    const id = current.current.id;
    const epoch = generation.current;
    try {
      const result = await history.investigation(id, new AbortController().signal);
      if (writing.current) await writing.current;
      if (!mergeRefresh(result, id, epoch)) return;
      if (actorWriting.current) await actorWriting.current;
      const preferences = await history.actorWorkspace();
      if (generation.current === epoch) {
        principal.current = preferences;
        setActor(preferences);
      }
    } catch {
      if (generation.current === epoch) setError('Could not refresh saved chat. Retry the read.');
    }
  }, [history]);

  useEffect(() => {
    const focus = () => {
      void refresh();
    };
    window.addEventListener('focus', focus);
    return () => window.removeEventListener('focus', focus);
  }, [refresh]);

  useEffect(() => {
    const controller = new AbortController();
    const epoch = ++generation.current;
    ++accountGeneration.current;
    const changedHistory = historyOwner.current !== history;
    if (changedHistory) {
      historyOwner.current = history;
      current.current = undefined;
      principal.current = undefined;
      pending.current = {};
      actorPending.current = {};
      writing.current = null;
      actorWriting.current = null;
      conflict.current = null;
      initialDraft.current = null;
      initialCreation.current = null;
    }
    queueMicrotask(() => {
      if (!controller.signal.aborted) {
        if (changedHistory) {
          setLoading(false);
          setActor(undefined);
          setDetail(undefined);
          showDraft('');
          setSaveState('saved');
        }
        setReady(!history);
        setError('');
      }
    });
    if (!history) return;
    void history
      .actorWorkspace(controller.signal)
      .then(async (value) => {
        if (controller.signal.aborted || generation.current !== epoch) return;
        principal.current = value;
        setActor(value);
        if (value.last_investigation_id) {
          const result = await history.investigation(value.last_investigation_id, controller.signal);
          if (!controller.signal.aborted && generation.current === epoch) install(result);
        }
        if (!controller.signal.aborted && generation.current === epoch) setReady(true);
      })
      .catch(() => {
        if (!controller.signal.aborted) setError('Could not restore saved workspace. Retry the read.');
      });
    return () => {
      controller.abort();
      active.current?.abort();
      clearPendingSave();
      // Invalidate the latest operation, including creates started after bootstrap.
      // eslint-disable-next-line react-hooks/exhaustive-deps
      generation.current++;
      // eslint-disable-next-line react-hooks/exhaustive-deps -- Invalidate the latest preference operation as well.
      accountGeneration.current++;
    };
  }, [history, attempt, install, clearPendingSave]);

  return {
    ready,
    loading,
    error,
    actor,
    detail,
    draft,
    saveState,
    open,
    create,
    patch,
    flush,
    refresh,
    setDraft: (value: string) => patch({ draft: value }),
    reloadConflict,
    useDraft,
    savePreferences,
    conflictWith,
    restoreDraft,
    retry: () => setAttempt((value) => value + 1),
    revision: () => current.current?.workspace.revision ?? 0,
  };
}
