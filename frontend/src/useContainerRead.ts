import { useCallback, useState, type Dispatch, type SetStateAction } from 'react';
import { ApiError } from './api';
import type { Container, LogBatch, Metrics, Transport } from './contracts';
import { usePolling, type PollResult, type ReadReason } from './usePolling';

export interface RuntimeRead<T> {
  data?: T;
  receivedAt?: string;
  loading: boolean;
  error?: string;
  missing?: boolean;
}

/** Refresh inspect automatically while keeping logs and metrics as independent manual observations. */
export function useContainerRead(client: Transport, host: string, id: string, automatic = false, active = true) {
  const [snapshot, setSnapshot] = useState<RuntimeRead<Container>>({ loading: true });
  const [logs, setLogs] = useState<RuntimeRead<LogBatch>>({ loading: true });
  const [metrics, setMetrics] = useState<RuntimeRead<Metrics>>({ loading: true });
  const collect = useCallback(
    async (signal: AbortSignal, reason: ReadReason): Promise<PollResult> => {
      /** Settle each source separately and retain observations after a failed request. */
      async function read<T>(
        pending: Promise<T>,
        update: Dispatch<SetStateAction<RuntimeRead<T>>>,
      ): Promise<PollResult> {
        try {
          const data = await pending;
          if (!signal.aborted) update({ data, receivedAt: new Date().toISOString(), loading: false });
          return 'success';
        } catch (error) {
          const missing = error instanceof ApiError && error.code === 'container_not_found' && error.httpStatus === 404;
          if (!signal.aborted)
            update((previous) => ({
              ...previous,
              loading: false,
              error: error instanceof Error ? error.message : 'Docker read failed.',
              missing: missing || previous.missing,
            }));
          return missing ? 'stop' : 'retry';
        }
      }

      if (reason !== 'automatic') {
        setSnapshot((previous) => ({ ...previous, loading: true }));
        setLogs((previous) => ({ ...previous, loading: true }));
        setMetrics((previous) => ({ ...previous, loading: true }));
      }
      const pending = [read(client.container(host, id, signal), setSnapshot)];
      if (reason !== 'automatic') {
        pending.push(read(client.logs(host, id, signal), setLogs), read(client.stats(host, id, signal), setMetrics));
      }
      const results = await Promise.all(pending);
      if (results[0] === 'stop') return 'stop';
      return results.includes('retry') ? 'retry' : 'success';
    },
    [client, host, id],
  );
  const refresh = usePolling(collect, automatic, active);

  return { snapshot, logs, metrics, refresh, loading: snapshot.loading || logs.loading || metrics.loading };
}
