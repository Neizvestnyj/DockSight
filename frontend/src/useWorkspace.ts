import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from './api';
import {
  actorWorkspaceSchema,
  investigationWorkspaceSchema,
  type ActorChanges,
  type ActorWorkspace,
  type HistoryTransport,
  type InvestigationDetail,
  type InvestigationWorkspace,
  type WorkspaceChanges,
} from './investigation-contracts';

type SaveState = 'saved' | 'unsaved' | 'saving' | 'conflict' | 'error';

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

  /** Commit pending local changes, stopping on conflicts and retaining dirty text. */
  async function flush(): Promise<boolean> {
    clearTimeout(timer.current);
    if (!history || !current.current || conflict.current) return !history;
    if (writing.current) {
      await writing.current;
      return flush();
    }
    const id = current.current.id;
    const epoch = generation.current;
    const operation = (async () => {
      while (Object.keys(pending.current).length && current.current?.id === id) {
        const patch = pending.current;
        pending.current = {};
        setSaveState('saving');
        try {
          const result = await history.saveWorkspace(id, current.current.workspace.revision, patch);
          if (generation.current !== epoch || current.current?.id !== id) return false;
          current.current = { ...current.current, workspace: result };
          setDetail(current.current);
          if (patch.draft !== undefined && pending.current.draft === undefined) showDraft(result.draft);
        } catch (failure) {
          if (generation.current !== epoch || current.current?.id !== id) return false;
          pending.current = { ...patch, ...pending.current };
          const parsed = investigationWorkspaceSchema.safeParse(failure instanceof ApiError ? failure.current : null);
          if (failure instanceof ApiError && failure.code === 'workspace_conflict' && parsed.success) {
            conflict.current = parsed.data;
            setSaveState('conflict');
          } else setSaveState('error');
          return false;
        }
      }
      if (generation.current === epoch) setSaveState('saved');
      return true;
    })();
    writing.current = operation;
    try {
      return await operation;
    } finally {
      if (writing.current === operation) writing.current = null;
    }
  }

  /** Queue a bounded draft or exact selection, with one debounce shared by local changes. */
  function patch(changes: WorkspaceChanges) {
    if (!current.current) return;
    pending.current = { ...pending.current, ...changes };
    if (changes.draft !== undefined) showDraft(changes.draft);
    if (!conflict.current) {
      setSaveState('unsaved');
      clearTimeout(timer.current);
      timer.current = setTimeout(() => {
        void flush();
      }, 300);
    }
  }

  /** Discard dirty local changes only through the explicit conflict control. */
  function reloadConflict() {
    if (current.current && conflict.current) install({ ...current.current, workspace: conflict.current });
  }

  /** Rebase only the operator's draft onto the current safe server workspace. */
  async function useDraft() {
    if (!current.current || !conflict.current) return;
    const local = pending.current.draft ?? draft;
    current.current = { ...current.current, workspace: conflict.current };
    conflict.current = null;
    pending.current = { draft: local };
    await flush();
  }

  /** Preserve the submitted local text when another tab wins submission admission. */
  function conflictWith(value: unknown) {
    const parsed = investigationWorkspaceSchema.safeParse(value);
    if (!parsed.success) {
      setSaveState('error');
      return;
    }
    conflict.current = parsed.data;
    pending.current = { ...pending.current, draft: pending.current.draft ?? draft };
    clearTimeout(timer.current);
    setSaveState('conflict');
  }

  /** Retain an unrelated composer draft after an explicit card-originated question. */
  async function restoreDraft(value: string) {
    if (pending.current.draft !== undefined || conflict.current || writing.current) return;
    patch({ draft: value });
    await flush();
  }

  /** Detach old reads before opening another owned archive. */
  async function open(id: string) {
    if (!history) return;
    clearTimeout(timer.current);
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    const epoch = ++generation.current;
    pending.current = {};
    conflict.current = null;
    setLoading(true);
    setError('');
    try {
      const result = await history.investigation(id, controller.signal);
      if (generation.current !== epoch || controller.signal.aborted) return;
      install(result);
      await savePreferences({ last_investigation_id: id, host: result.host });
    } catch {
      if (generation.current === epoch && !controller.signal.aborted)
        setError('Could not open saved chat. Retry the read.');
    } finally {
      if (generation.current === epoch) setLoading(false);
    }
  }

  /** Create one explicit chat without deleting any previous archive. */
  async function create(host: string) {
    if (!history || !host) return;
    active.current?.abort();
    const epoch = ++generation.current;
    clearTimeout(timer.current);
    pending.current = {};
    setLoading(true);
    setError('');
    try {
      const result = await history.createInvestigation(crypto.randomUUID(), host);
      if (generation.current !== epoch) return;
      install({ ...result, turns: { items: [], next_cursor: null } });
      await savePreferences({ last_investigation_id: result.id, host });
    } catch {
      if (generation.current === epoch) setError('Could not create saved chat. Retry manually.');
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
      if (generation.current !== epoch || current.current?.id !== id) return;
      current.current = {
        ...result,
        workspace:
          result.workspace.revision >= current.current.workspace.revision
            ? result.workspace
            : current.current.workspace,
      };
      setDetail(current.current);
      if (!Object.keys(pending.current).length && !writing.current && !conflict.current)
        showDraft(current.current.workspace.draft);
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
    const accountEpoch = ++accountGeneration.current;
    queueMicrotask(() => {
      if (!controller.signal.aborted) {
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
      clearTimeout(timer.current);
      generation.current = epoch + 1;
      accountGeneration.current = accountEpoch + 1;
    };
  }, [history, attempt, install]);

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
