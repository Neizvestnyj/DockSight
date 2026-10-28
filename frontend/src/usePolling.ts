import { useCallback, useEffect, useRef, useState } from 'react';

export type PollResult = 'success' | 'retry' | 'stop' | 'unavailable';
export type ReadReason = 'initial' | 'manual' | 'automatic';

interface PollingOptions {
  interval?: number;
  maxInterval?: number;
  staleAfter?: number;
}

/** Schedule one cancellable runtime read at a time. */
export function usePolling(
  read: (signal: AbortSignal, reason: ReadReason) => Promise<PollResult>,
  automatic: boolean,
  active = true,
  { interval = 10_000, maxInterval = 60_000, staleAfter = 0 }: PollingOptions = {},
) {
  const manual = useRef<() => void>(() => {});
  const stale = useRef<() => void>(() => {});
  const [activity, setActivity] = useState({ read, fetching: false, stopped: false, interactive: false });

  useEffect(() => {
    if (!active) return;
    let controller: AbortController | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let disposed = false;
    let stopped = false;
    let pendingManual = false;
    let failures = 0;
    let lastCompleted: number | undefined;
    let nextReadAt = 0;

    /** Read only while the page can display fresh observations. */
    function canPoll() {
      return automatic && !stopped && document.visibilityState === 'visible' && navigator.onLine;
    }

    /** Wait after settlement so slow requests cannot accumulate. */
    function schedule() {
      clearTimeout(timer);
      if (canPoll()) timer = setTimeout(() => void run('automatic'), Math.max(0, nextReadAt - Date.now()));
    }

    /** Let the owner handle errors and publish data before scheduling its next read. */
    async function run(reason: ReadReason) {
      if (disposed || controller || (reason === 'automatic' && !canPoll())) return;
      clearTimeout(timer);
      controller = new AbortController();
      setActivity({ read, fetching: true, stopped, interactive: reason !== 'automatic' });
      const result = await read(controller.signal, reason);
      if (disposed) return;
      controller = undefined;
      failures = result === 'retry' || result === 'unavailable' ? Math.min(failures + 1, 3) : 0;
      if (result !== 'retry') stopped = result === 'stop';
      lastCompleted = Date.now();
      nextReadAt = lastCompleted + Math.min(interval * 2 ** failures, maxInterval);
      setActivity({ read, fetching: false, stopped, interactive: false });
      if (pendingManual) {
        pendingManual = false;
        void run('manual');
        return;
      }
      schedule();
    }

    /** Read on access only when the last attempt is old enough for this source. */
    function refreshIfStale() {
      if (lastCompleted === undefined || Date.now() - lastCompleted >= staleAfter) void run('automatic');
    }

    /** Keep the existing deadline when returning to a still-fresh observation. */
    function resume() {
      if (canPoll()) refreshIfStale();
      if (!controller) schedule();
      else clearTimeout(timer);
    }

    /** A deliberate retry may restart a resource whose automatic reads stopped. */
    function refresh() {
      if (controller) {
        pendingManual = true;
        setActivity({ read, fetching: true, stopped, interactive: true });
        return;
      }
      void run('manual');
    }

    manual.current = refresh;
    stale.current = refreshIfStale;
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
      stale.current = () => {};
      document.removeEventListener('visibilitychange', resume);
      window.removeEventListener('focus', resume);
      window.removeEventListener('online', resume);
      window.removeEventListener('offline', resume);
    };
  }, [read, automatic, active, interval, maxInterval, staleAfter]);

  return {
    refresh: useCallback(() => manual.current(), []),
    refreshIfStale: useCallback(() => stale.current(), []),
    fetching: active && activity.read === read && activity.fetching,
    stopped: active && activity.read === read && activity.stopped,
    interactive: active && activity.read === read && activity.interactive,
  };
}
