import { useCallback, useEffect, useRef, useState } from 'react';
import type { HistoryTransport, InvestigationSummary } from './investigation-contracts';

/** Page owned server history independently of the active tab's navigation. */
export function useSavedInvestigations(history?: HistoryTransport) {
  const [items, setItems] = useState<InvestigationSummary[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(Boolean(history));
  const [error, setError] = useState('');
  const generation = useRef(0);
  const pages = useRef(0);
  const busy = useRef(false);
  const active = useRef<AbortController | null>(null);

  /** Refresh the latest page while retaining already loaded older stable pages. */
  const refresh = useCallback(async () => {
    if (!history || busy.current) return;
    const epoch = generation.current;
    const controller = new AbortController();
    active.current = controller;
    busy.current = true;
    setLoading(true);
    try {
      const result = await history.investigations(controller.signal);
      if (epoch !== generation.current || controller.signal.aborted) return;
      setItems((previous) => (pages.current > 1 ? merge(result.items, previous) : result.items));
      if (pages.current <= 1) setNextCursor(result.next_cursor);
      pages.current = Math.max(pages.current, 1);
      setError('');
    } catch {
      if (epoch === generation.current && !controller.signal.aborted) setError('Could not load saved chats.');
    } finally {
      if (epoch === generation.current) {
        busy.current = false;
        setLoading(false);
      }
    }
  }, [history]);

  /** Append the next explicit page with exact-ID deduplication. */
  async function older() {
    if (!history || !nextCursor || busy.current) return;
    const epoch = generation.current;
    const controller = new AbortController();
    active.current = controller;
    busy.current = true;
    setLoading(true);
    try {
      const result = await history.investigations(controller.signal, nextCursor);
      if (epoch !== generation.current || controller.signal.aborted) return;
      setItems((previous) => merge(previous, result.items));
      setNextCursor(result.next_cursor);
      pages.current++;
      setError('');
    } catch {
      if (epoch === generation.current && !controller.signal.aborted) setError('Could not load saved chats.');
    } finally {
      if (epoch === generation.current) {
        busy.current = false;
        setLoading(false);
      }
    }
  }

  /** Remove only an explicitly confirmed archive and then refresh activity ordering. */
  async function remove(id: string): Promise<boolean> {
    if (!history) return false;
    const epoch = generation.current;
    try {
      await history.deleteInvestigation(id);
      if (epoch !== generation.current) return false;
      setItems((previous) => previous.filter((row) => row.id !== id));
      await refresh();
      return true;
    } catch {
      if (epoch === generation.current)
        setError('Could not delete chat. Running diagnoses must finish or be stopped first.');
      return false;
    }
  }

  useEffect(() => {
    const epoch = ++generation.current;
    pages.current = 0;
    busy.current = false;
    queueMicrotask(() => {
      if (generation.current === epoch) {
        setItems([]);
        setNextCursor(null);
        void refresh();
      }
    });
    const onFocus = () => {
      void refresh();
    };
    window.addEventListener('focus', onFocus);
    return () => {
      generation.current = epoch + 1;
      active.current?.abort();
      window.removeEventListener('focus', onFocus);
    };
  }, [refresh]);

  return { items, nextCursor, loading, error, refresh, older, remove };
}

/** Preserve page order while treating repeated IDs as the same saved object. */
function merge(first: InvestigationSummary[], second: InvestigationSummary[]) {
  const seen = new Set(first.map((row) => row.id));
  return [...first, ...second.filter((row) => !seen.has(row.id))];
}
