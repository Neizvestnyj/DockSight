import { useCallback, useEffect, useRef, useState } from 'react';
import type { Container, Transport } from './contracts';
import { usePolling, type PollResult, type ReadReason } from './usePolling';

/** Refresh the host read model without changing diagnostic observations or navigation. */
export function useInventory(client: Transport, host: string, automatic: boolean) {
  const [inventory, setInventory] = useState<Container[]>([]);
  const [loading, setLoading] = useState(true);
  const [inventoryError, setInventoryError] = useState('');
  const [lastRefreshed, setLastRefreshed] = useState<string>();
  const [refreshAcknowledged, setRefreshAcknowledged] = useState(0);
  const acknowledgements = useRef(0);

  const read = useCallback(
    async (signal: AbortSignal, reason: ReadReason): Promise<PollResult> => {
      if (reason !== 'automatic') {
        setLoading(true);
        setRefreshAcknowledged(0);
      }
      try {
        const rows = await client.containers(host, signal);
        if (!signal.aborted) {
          setInventory(rows);
          setInventoryError('');
          setLoading(false);
          setLastRefreshed(new Date().toISOString());
          if (reason === 'manual') setRefreshAcknowledged(++acknowledgements.current);
        }
        return 'success';
      } catch (error) {
        if (!signal.aborted) {
          setInventoryError(error instanceof Error ? error.message : 'Could not read Docker inventory.');
          setLoading(false);
        }
        return 'retry';
      }
    },
    [client, host],
  );
  const refresh = usePolling(read, automatic, Boolean(host));

  useEffect(() => {
    if (!refreshAcknowledged) return;
    const timer = setTimeout(() => setRefreshAcknowledged(0), 2000);
    return () => clearTimeout(timer);
  }, [refreshAcknowledged]);

  return { inventory, loading, inventoryError, lastRefreshed, refreshAcknowledged, refresh };
}
