import type { RefObject } from 'react';
import { ApiError } from '../../../shared/contracts/errors';
import {
  investigationWorkspaceSchema,
  type HistoryTransport,
  type InvestigationDetail,
  type InvestigationWorkspace,
  type WorkspaceChanges,
} from '../../../shared/contracts/investigation-contracts';

export type SaveState = 'saved' | 'unsaved' | 'saving' | 'conflict' | 'error';

export interface InitialDraft {
  value: string;
  host: string | null;
  epoch: number | null;
}

export interface InitialCreation {
  host: string;
  epoch: number;
}

interface WriteContext {
  history?: HistoryTransport;
  current: RefObject<InvestigationDetail | undefined>;
  pending: RefObject<WorkspaceChanges>;
  writing: RefObject<Promise<boolean> | null>;
  conflict: RefObject<InvestigationWorkspace | null>;
  generation: RefObject<number>;
  timer: RefObject<ReturnType<typeof setTimeout> | undefined>;
  initialDraft: RefObject<InitialDraft | null>;
  initialCreation: RefObject<InitialCreation | null>;
  provisionalChat: RefObject<{ id: string } | undefined>;
  draft: string;
  showDraft: (value: string) => void;
  setSaveState: (value: SaveState) => void;
  setDetail: (value: InvestigationDetail) => void;
  install: (value: InvestigationDetail) => void;
}

/** Serialize revisioned writes while navigation retains ownership of the current scope. */
export function useWorkspaceWrites({
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
}: WriteContext) {
  /** Retain failed changes only while the initiating workspace still owns the write. */
  function failWrite(failure: unknown, patch: WorkspaceChanges, id: string, epoch: number): false {
    if (generation.current !== epoch || current.current?.id !== id) return false;
    pending.current = { ...patch, ...pending.current };
    const parsed = investigationWorkspaceSchema.safeParse(failure instanceof ApiError ? failure.current : null);
    if (failure instanceof ApiError && failure.code === 'workspace_conflict' && parsed.success) {
      conflict.current = parsed.data;
      setSaveState('conflict');
    } else setSaveState('error');
    return false;
  }

  /** Commit pending local changes, stopping on conflicts and retaining dirty text. */
  async function flush(): Promise<boolean> {
    clearTimeout(timer.current);
    if (!history || !current.current) return true;
    if (conflict.current) return false;
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
          return failWrite(failure, patch, id, epoch);
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

  /** Keep draft text and selection with their local editor before any server acknowledgement. */
  function patchInitial(changes: WorkspaceChanges) {
    if (provisionalChat.current) pending.current = { ...pending.current, ...changes };
    if (changes.draft === undefined || !history) return;
    initialDraft.current = {
      value: changes.draft,
      host: initialCreation.current?.host ?? initialDraft.current?.host ?? null,
      epoch: initialCreation.current?.epoch ?? initialDraft.current?.epoch ?? null,
    };
    showDraft(changes.draft);
    setSaveState('unsaved');
  }

  /** Queue a bounded draft or exact selection, with one debounce shared by local changes. */
  function patch(changes: WorkspaceChanges) {
    if (!current.current) return patchInitial(changes);
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

  return { flush, patch, reloadConflict, useDraft, conflictWith, restoreDraft };
}
