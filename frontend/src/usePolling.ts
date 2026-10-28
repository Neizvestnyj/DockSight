import { useCallback, useEffect, useRef } from 'react';

export type PollResult = 'success' | 'retry' | 'stop';
export type ReadReason = 'initial' | 'manual' | 'automatic';

/** Schedule one cancellable runtime read at a time. */
export function usePolling(
  read: (signal: AbortSignal, reason: ReadReason) => Promise<PollResult>,
  automatic: boolean,
  active = true,
): () => void {
  const manual = useRef<() => void>(() => {});

  useEffect(() => {
    if (!active) return;
    let controller: AbortController | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let disposed = false;
    let stopped = false;
    let pendingManual = false;
    let failures = 0;

    /** Read only while the page can display fresh observations. */
    function canPoll() {
      return automatic && !stopped && document.visibilityState === 'visible' && navigator.onLine;
    }

    /** Wait after settlement so slow requests cannot accumulate. */
    function schedule() {
      if (canPoll()) timer = setTimeout(() => void run('automatic'), Math.min(10_000 * 2 ** failures, 60_000));
    }

    /** Let the owner handle errors and publish data before scheduling its next read. */
    async function run(reason: ReadReason) {
      if (disposed || controller || (reason === 'automatic' && !canPoll())) return;
      clearTimeout(timer);
      controller = new AbortController();
      const result = await read(controller.signal, reason);
      if (disposed) return;
      controller = undefined;
      failures = result === 'retry' ? Math.min(failures + 1, 3) : 0;
      if (result !== 'retry') stopped = result === 'stop';
      if (pendingManual) {
        pendingManual = false;
        void run('manual');
        return;
      }
      schedule();
    }

    /** Resume immediately on foreground or connectivity restoration. */
    function resume() {
      clearTimeout(timer);
      if (canPoll()) void run('automatic');
    }

    /** A deliberate retry may restart a resource whose automatic reads stopped. */
    function refresh() {
      if (controller) {
        pendingManual = true;
        return;
      }
      void run('manual');
    }

    manual.current = refresh;
    void run('initial');
    document.addEventListener('visibilitychange', resume);
    window.addEventListener('focus', resume);
    window.addEventListener('online', resume);
    window.addEventListener('offline', resume);
    return () => {
      disposed = true;
      controller?.abort();
      clearTimeout(timer);
      manual.current = () => {};
      document.removeEventListener('visibilitychange', resume);
      window.removeEventListener('focus', resume);
      window.removeEventListener('online', resume);
      window.removeEventListener('offline', resume);
    };
  }, [read, automatic, active]);

  return useCallback(() => manual.current(), []);
}
