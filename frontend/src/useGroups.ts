import { useEffect, useState } from 'react';
import type { GroupTarget, Stack, Transport } from './contracts';

export type GroupKind = 'all' | GroupTarget['kind'];

/** Keep explicit group selection independent of drafts, historical turns, and automatic inventory reads. */
export function useGroups(client: Transport, host: string, initial?: GroupTarget) {
  const [kind, setKind] = useState<GroupKind>(initial?.kind ?? 'all');
  const [name, setName] = useState(initial?.name ?? '');
  const [groups, setGroups] = useState<Stack[]>([]);
  const [loading, setLoading] = useState(Boolean(initial && host));
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (kind === 'all' || !host) return;
    const controller = new AbortController();
    client
      .stacks(host, kind, controller.signal)
      .then((rows) => {
        if (!controller.signal.aborted) {
          setGroups(rows);
          setLoading(false);
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setError(true);
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [client, host, kind, attempt]);

  /** Clear only the filter when changing resource kind, leaving investigations untouched. */
  function changeKind(value: GroupKind) {
    setKind(value);
    setName('');
    setGroups([]);
    setError(false);
    setLoading(value !== 'all' && Boolean(host));
  }
  const group = groups.find((row) => row.kind === kind && row.name === name);
  return {
    kind,
    groups,
    group,
    loading,
    error,
    changeKind,
    choose: (value: string) => setName(value),
    refresh: () => {
      setLoading(true);
      setError(false);
      setAttempt((n) => n + 1);
    },
  };
}
