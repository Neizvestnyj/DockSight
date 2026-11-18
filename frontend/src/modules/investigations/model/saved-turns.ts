import type { SavedTurn, TurnPage } from '../../../shared/contracts/investigation-contracts';
import type { Turn } from './turns';

/** Group clarification attempts under one original question without discarding attempt metadata. */
export function projectSavedTurns(snapshots: TurnPage['items']): Turn[] {
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
    groups.set(root, projectSavedTurn(row, previous));
  }
  return [...groups.values()];
}

/** Preserve the original question while projecting the latest retained attempt. */
function projectSavedTurn(row: SavedTurn, previous: Turn | undefined): Turn {
  return {
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
    trace: savedTrace(row),
    createdAt: previous?.createdAt ?? row.created_at,
    updatedAt: row.updated_at,
    attempts: [...(previous?.attempts ?? []), row],
  };
}

/** Keep trace metadata attached to the saved attempt that produced it. */
function savedTrace(row: SavedTurn): NonNullable<Turn['trace']> {
  return {
    provider: row.model?.provider ?? null,
    model: row.model?.model ?? null,
    started_at: row.created_at,
    steps: row.trace,
  };
}
