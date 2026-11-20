import { useEffect, useRef, useState } from 'react';
import type { SavedTurn } from '../../../shared/contracts/investigation-contracts';
import { projectSavedTurns } from './saved-turns';
import type { Turn } from './turns';

interface Selection {
  id?: string;
  latest?: string;
  searchTurn?: SavedTurn;
}

/** Display a selected question without changing the active turn or the history cursor. */
export function useQuestionView(turns: Turn[], searchTurn?: SavedTurn, active = true) {
  const [selection, setSelection] = useState<Selection>();
  const latest = turns.at(-1);
  const anchor = selection?.searchTurn !== searchTurn ? searchTurn : undefined;
  const question = useRef<HTMLHeadingElement>(null);
  const loadedMatch =
    anchor && turns.find((row) => row.id === anchor.id || row.attempts?.some(({ id }) => id === anchor.id));
  const turn = anchor ? (loadedMatch ?? projectSavedTurns([anchor])[0]) : selectTurn(turns, latest, selection);

  useEffect(() => {
    if (anchor && active) question.current?.focus();
  }, [anchor, active]);

  /** Return to normal navigation when the operator leaves the search match. */
  function chooseView(id?: string) {
    setSelection({ id, latest: latest?.id, searchTurn });
  }

  return {
    turn,
    question,
    chooseView,
    anchoring: Boolean(anchor && turn?.id !== latest?.id),
    readOnlyAnchor: Boolean(anchor && !loadedMatch),
  };
}

/** Keep manual history selection tied to the latest turn present when selected. */
function selectTurn(turns: Turn[], latest: Turn | undefined, selection?: Selection) {
  return (selection?.latest === latest?.id && turns.find((row) => row.id === selection?.id)) || latest;
}
