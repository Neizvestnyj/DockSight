import { useCallback, useEffect, useRef, useState } from 'react';
import type { DiagnosticTarget } from '../../../shared/contracts/contracts';
import { ApiError } from '../../../shared/contracts/errors';
import {
  actorWorkspaceSchema,
  type ActorChanges,
  type ActorWorkspace,
  type HistoryTransport,
  type InvestigationDetail,
  type InvestigationView,
  type InvestigationWorkspace,
  type SavedTurn,
  type WorkspaceChanges,
} from '../../../shared/contracts/investigation-contracts';

import { useWorkspaceWrites, type InitialCreation, type InitialDraft, type SaveState } from './workspace-writes';

interface InitialDiagnosis {
  query: string;
  target: DiagnosticTarget;
}

interface DraftChat {
  id: string;
  host: string;
}

interface CreationIntent {
  localId?: string;
  diagnosis?: InitialDiagnosis;
}

/** Keep acknowledged server revisions separate from unsent text and serialize local writes. */
export function useWorkspace(history?: HistoryTransport, onDraftCreated?: () => Promise<void>) {
  const [ready, setReady] = useState(!history);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [actor, setActor] = useState<ActorWorkspace>();
  const [detail, setDetail] = useState<InvestigationDetail>();
  const [search, setSearch] = useState<{ turn?: SavedTurn }>();
  const [draftChat, setDraftChat] = useState<DraftChat>();
  const [diagnosisChatId, setDiagnosisChatId] = useState<string>();
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
  const pendingDiagnosis = useRef<(InitialDiagnosis & { id: string; epoch: number }) | undefined>(undefined);
  const accountGeneration = useRef(0);
  const active = useRef<AbortController | null>(null);
  const activeQuestion = useRef<AbortController | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const initialDraft = useRef<InitialDraft | null>(null);
  const initialCreation = useRef<InitialCreation | null>(null);
  const provisionalChat = useRef<DraftChat | undefined>(undefined);
  const draftCreation = useRef<{ intent: CreationIntent; operation: Promise<void> } | undefined>(undefined);
  const historyOwner = useRef(history);
  const clearPendingSave = useCallback(() => clearTimeout(timer.current), []);
  const detachReads = useCallback(() => {
    active.current?.abort();
    activeQuestion.current?.abort();
  }, []);

  /** Install an acknowledged workspace or clear it before opening a local editor. */
  const install = useCallback((value?: InvestigationDetail, fromSearch?: { turn?: SavedTurn }) => {
    current.current = value;
    provisionalChat.current = undefined;
    setDraftChat(undefined);
    pending.current = {};
    conflict.current = null;
    setDetail(value);
    setSearch(fromSearch);
    showDraft(value?.workspace.draft ?? '');
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
    provisionalChat,
    draft,
    showDraft,
    setSaveState,
    setDetail,
    install,
  });

  /** Wait for typed text to have an acknowledged owner before leaving the editor. */
  async function flushNavigation(): Promise<boolean> {
    if (draftCreation.current) await draftCreation.current.operation;
    if (provisionalChat.current && initialDraft.current?.value.trim()) return false;
    return flush();
  }

  /** Open a local editor or focus the same host's empty chat again. */
  async function beginDraft(host: string): Promise<boolean> {
    if (!history || !host || !(await flushNavigation())) return false;
    const chat = current.current;
    if (provisionalChat.current?.host === host || (chat?.host === host && !chat.turn_count && !chat.workspace.draft))
      return true;
    detachReads();
    generation.current++;
    initialDraft.current = null;
    initialCreation.current = null;
    install();
    provisionalChat.current = { id: crypto.randomUUID(), host };
    setDraftChat(provisionalChat.current);
    setLoading(false);
    setError('');
    return true;
  }

  /** Commit the local editor once text is entered, retaining its ID through retries. */
  async function saveNewDraft() {
    const chat = provisionalChat.current;
    if (!chat || !initialDraft.current?.value.trim() || draftCreation.current) return;
    await create(chat.host, undefined, chat.id);
    if (current.current?.id === chat.id) void onDraftCreated?.();
  }

  /** Queue the draft without allocating durable storage for an untouched editor. */
  function setDraft(value: string) {
    patch({ draft: value });
    void saveNewDraft();
  }

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

  /** Read a question in the current chat without detaching its active diagnosis. */
  async function openCurrentQuestion(history: HistoryTransport, chat: InvestigationDetail, turnId: string) {
    const controller = new AbortController();
    const epoch = generation.current;
    activeQuestion.current = controller;
    setError('');
    try {
      const result = await history.turn(turnId, controller.signal);
      if (detached(epoch, controller.signal)) return false;
      verifyQuestion(chat, result);
      setSearch({ turn: result });
      return true;
    } catch {
      if (!detached(epoch, controller.signal)) setError('Could not open saved chat. Retry the read.');
      return false;
    }
  }

  /** Open an archive from the recent chat list. */
  async function open(id: string) {
    if (history) await openArchive(history, id);
  }

  /** Keep same-chat search navigation independent of workspace and turn ownership. */
  async function openResult(id: string, turnId: string | null) {
    if (!history) return false;
    activeQuestion.current?.abort();
    const chat = current.current;
    if (chat?.id === id && !loading) {
      if (turnId) return openCurrentQuestion(history, chat, turnId);
      setSearch({});
      return true;
    }
    return openArchive(history, id, turnId);
  }

  /** Detach old reads before opening another owned archive. */
  async function openArchive(history: HistoryTransport, id: string, turnId?: string | null) {
    if (!(await flushNavigation())) return false;
    const openingInitial = !current.current;
    detachReads();
    const controller = new AbortController();
    active.current = controller;
    const epoch = ++generation.current;
    setLoading(true);
    setError('');
    try {
      const { result, matchedTurn } = await readArchive(history, id, controller.signal, turnId);
      if (detached(epoch, controller.signal)) return false;
      if (!(await flush()) || detached(epoch, controller.signal)) return false;
      const workspace = currentWorkspace(id, result);
      if (openingInitial) {
        initialDraft.current = null;
        initialCreation.current = null;
      }
      install({ ...result, workspace }, searchSelection(turnId, matchedTurn));
      await savePreferences({ last_investigation_id: id });
      return !detached(epoch, controller.signal);
    } catch {
      if (!detached(epoch, controller.signal)) {
        if (openingInitial && !current.current) {
          initialCreation.current = null;
          if (initialDraft.current) initialDraft.current = { ...initialDraft.current, epoch: null };
        }
        setError('Could not open saved chat. Retry the read.');
      }
      return false;
    } finally {
      if (generation.current === epoch) setLoading(false);
    }
  }

  /** Take ownership of the read and any text entered while creation is in flight. */
  function beginCreation(host: string) {
    detachReads();
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
    return { initial, epoch };
  }

  /** Replay changes only into the acknowledged ID that owned the local editor. */
  function installCreated(result: InvestigationView, initial: boolean, epoch: number, localId?: string) {
    const retained = takeInitialDraft(initial, epoch);
    const changes: WorkspaceChanges = localId ? pending.current : {};
    if (retained !== undefined) changes.draft = retained;
    install({ ...result, turns: { items: [], next_cursor: null } });
    if (Object.keys(changes).length) patch(changes);
  }

  /** Only an exact local draft ID may be used without first saving the current editor. */
  async function canCreate(localId?: string) {
    if (!localId) return flushNavigation();
    return (await flush()) && provisionalChat.current?.id === localId;
  }

  /** Use the open draft's ID when an explicit diagnosis creates it. */
  function creationId(host: string, diagnosis?: InitialDiagnosis, draftId?: string) {
    const draft = provisionalChat.current;
    return draftId ?? (diagnosis && draft?.host === host ? draft.id : undefined);
  }

  /** Make an initial diagnosis claimable once its exact chat has mounted. */
  function queueDiagnosis(id: string, epoch: number, diagnosis: InitialDiagnosis) {
    pendingDiagnosis.current = { id, epoch, ...diagnosis };
    setDiagnosisChatId(id);
  }

  /** Keep one in-flight creation per local editor, including a diagnosis requested during its first save. */
  function create(host: string, diagnosis?: InitialDiagnosis, draftId?: string) {
    const localId = creationId(host, diagnosis, draftId);
    const intent: CreationIntent = { localId, diagnosis };
    if (!localId) return createInvestigation(host, intent);
    const ongoing = draftCreation.current;
    if (ongoing?.intent.localId === localId) {
      ongoing.intent.diagnosis ??= diagnosis;
      return ongoing.operation;
    }
    const operation = createInvestigation(host, intent).finally(() => {
      if (draftCreation.current?.intent === intent) draftCreation.current = undefined;
    });
    draftCreation.current = { intent, operation };
    return operation;
  }

  /** Create one explicit chat and hand its ID to a caller only while this navigation still owns it. */
  async function createInvestigation(host: string, intent: CreationIntent) {
    if (!history || !host) return;
    const { localId } = intent;
    if (!(await canCreate(localId))) return;
    const { initial, epoch } = beginCreation(host);
    try {
      const result = await history.createInvestigation(localId ?? crypto.randomUUID(), host);
      if (generation.current !== epoch) return;
      if (!(await flush()) || generation.current !== epoch) return;
      installCreated(result, initial, epoch, localId);
      if (intent.diagnosis) queueDiagnosis(result.id, epoch, intent.diagnosis);
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

  /** Claim the initial question once from the matching chat after its workspace mounts. */
  function takeDiagnosis(id: string) {
    const pending = pendingDiagnosis.current;
    if (pending?.id !== id || pending.epoch !== generation.current || current.current?.id !== id) return;
    pendingDiagnosis.current = undefined;
    setDiagnosisChatId(undefined);
    return pending;
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
      provisionalChat.current = undefined;
      draftCreation.current = undefined;
    }
    queueMicrotask(() => {
      if (!controller.signal.aborted) {
        if (changedHistory) {
          setLoading(false);
          setActor(undefined);
          setDetail(undefined);
          setDraftChat(undefined);
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
      detachReads();
      clearPendingSave();
      // Invalidate the latest operation, including creates started after bootstrap.
      // eslint-disable-next-line react-hooks/exhaustive-deps
      generation.current++;
      // eslint-disable-next-line react-hooks/exhaustive-deps -- Invalidate the latest preference operation as well.
      accountGeneration.current++;
    };
  }, [history, attempt, install, clearPendingSave, detachReads]);

  return {
    ready,
    loading,
    error,
    actor,
    detail,
    searchOpened: Boolean(search),
    searchTurn: search?.turn,
    chat: detail ?? draftChat,
    draftChat,
    draft,
    saveState,
    open,
    openResult,
    create,
    beginDraft,
    saveNewDraft,
    diagnosisChatId,
    takeDiagnosis,
    patch,
    flush,
    refresh,
    setDraft,
    reloadConflict,
    useDraft,
    savePreferences,
    conflictWith,
    restoreDraft,
    retry: () => setAttempt((value) => value + 1),
    revision: () => current.current?.workspace.revision ?? 0,
  };
}

/** Read a matched question independently of the latest page and verify its exact chat. */
async function readArchive(history: HistoryTransport, id: string, signal: AbortSignal, turnId?: string | null) {
  const [result, matchedTurn] = await Promise.all([
    history.investigation(id, signal),
    turnId ? history.turn(turnId, signal) : undefined,
  ]);
  if (matchedTurn) verifyQuestion(result, matchedTurn);
  return { result, matchedTurn };
}

/** Reject a mismatched saved search result before showing it under a chat. */
function verifyQuestion(chat: InvestigationDetail, question: SavedTurn) {
  if (question.investigation_id !== chat.id || question.host !== chat.host)
    throw new Error('Search result is outside the selected investigation.');
}

/** Distinguish a title-only hit from ordinary archive navigation. */
function searchSelection(turnId?: string | null, turn?: SavedTurn) {
  return turnId === undefined ? undefined : { turn };
}
