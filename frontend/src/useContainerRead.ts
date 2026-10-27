import { useEffect, useState, type Dispatch, type SetStateAction } from 'react';
import type { Container, LogBatch, Metrics, Transport } from './contracts';

export interface RuntimeRead<T> {
  data?: T;
  receivedAt?: string;
  loading: boolean;
  error?: string;
}

/** Fetch independent Docker observations; stale responses never cross a container or host boundary. */
export function useContainerRead(client: Transport, host: string, id: string) {
  const [snapshot, setSnapshot] = useState<RuntimeRead<Container>>({ loading: true });
  const [logs, setLogs] = useState<RuntimeRead<LogBatch>>({ loading: true });
  const [metrics, setMetrics] = useState<RuntimeRead<Metrics>>({ loading: true });
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();

    /** Settle each source separately, retaining the previous successful response after failure. */
    async function read<T>(pending: Promise<T>, update: Dispatch<SetStateAction<RuntimeRead<T>>>) {
      try {
        const data = await pending;
        if (!controller.signal.aborted) update({ data, receivedAt: new Date().toISOString(), loading: false });
      } catch (error) {
        if (!controller.signal.aborted)
          update((previous) => ({
            ...previous,
            loading: false,
            error: error instanceof Error ? error.message : 'Docker read failed.',
          }));
      }
    }

    void read(client.container(host, id, controller.signal), setSnapshot);
    void read(client.logs(host, id, controller.signal), setLogs);
    void read(client.stats(host, id, controller.signal), setMetrics);
    return () => controller.abort();
  }, [client, host, id, revision]);

  /** Refresh the current read view only; diagnostic answers remain immutable snapshots. */
  function refresh() {
    setSnapshot((previous) => ({ ...previous, loading: true, error: undefined }));
    setLogs((previous) => ({ ...previous, loading: true, error: undefined }));
    setMetrics((previous) => ({ ...previous, loading: true, error: undefined }));
    setRevision((value) => value + 1);
  }

  return { snapshot, logs, metrics, refresh, loading: snapshot.loading || logs.loading || metrics.loading };
}
