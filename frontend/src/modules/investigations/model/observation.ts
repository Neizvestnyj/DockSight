/** Wait for visibility and connectivity without polling or admitting new work. */
export async function available(signal: AbortSignal): Promise<void> {
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
export async function delay(milliseconds: number, signal: AbortSignal) {
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
