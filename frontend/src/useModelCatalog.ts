import { useCallback, useEffect, useRef, useState } from 'react';
import type { Transport } from './contracts';
import type { ModelCatalog, ModelProviders, ProviderId } from './model-contracts';

interface CatalogRead {
  data?: ModelCatalog;
  loading: boolean;
  error: boolean;
}

/** Retain catalogs for this workspace, coalesce reads and cancel work when its connection closes. */
export function useModelCatalog(client: Transport) {
  const [providers, setProviders] = useState<ModelProviders>();
  const [providerError, setProviderError] = useState(false);
  const [catalogs, setCatalogs] = useState<Partial<Record<ProviderId, CatalogRead>>>({});
  const cache = useRef(new Map<ProviderId, { data: ModelCatalog; expires: number }>());
  const pending = useRef(new Map<string, Promise<void>>());
  const controllers = useRef(new Set<AbortController>());
  const knownProviders = useRef<ModelProviders>(undefined);

  useEffect(() => {
    const active = controllers.current;
    return () => {
      active.forEach((controller) => controller.abort());
    };
  }, [client]);

  const loadProviders = useCallback(() => {
    if (knownProviders.current) return Promise.resolve();
    const existing = pending.current.get('providers');
    if (existing) return existing;
    const controller = new AbortController();
    controllers.current.add(controller);
    setProviderError(false);
    const work = client
      .modelProviders(controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return;
        knownProviders.current = data;
        setProviders(data);
      })
      .catch(() => {
        if (!controller.signal.aborted) setProviderError(true);
      })
      .finally(() => {
        controllers.current.delete(controller);
        pending.current.delete('providers');
      });
    pending.current.set('providers', work);
    return work;
  }, [client]);

  const loadCatalog = useCallback(
    (provider: ProviderId, refresh = false) => {
      const existing = pending.current.get(provider);
      if (existing) return existing;
      const previous = cache.current.get(provider);
      if (!refresh && previous && previous.expires > Date.now()) return Promise.resolve();
      const controller = new AbortController();
      controllers.current.add(controller);
      setCatalogs((rows) => ({ ...rows, [provider]: { data: previous?.data, loading: true, error: false } }));

      /** Observe a bounded background refresh while retaining its immediately returned stale rows. */
      async function read() {
        try {
          for (let attempt = 0; attempt < 8; attempt++) {
            const data = await client.models(provider, controller.signal, refresh && attempt === 0);
            if (controller.signal.aborted) return;
            cache.current.set(provider, {
              data,
              expires: Date.now() + (data.refreshing ? 0 : data.code === 'ok' ? 300_000 : 30_000),
            });
            setCatalogs((rows) => ({ ...rows, [provider]: { data, loading: data.refreshing, error: false } }));
            if (!data.refreshing) return;
            await new Promise((resolve) => setTimeout(resolve, 800));
            controller.signal.throwIfAborted();
          }
        } catch {
          if (!controller.signal.aborted)
            setCatalogs((rows) => ({
              ...rows,
              [provider]: { data: cache.current.get(provider)?.data, loading: false, error: true },
            }));
        } finally {
          if (!controller.signal.aborted)
            setCatalogs((rows) => ({
              ...rows,
              [provider]: { ...rows[provider], loading: false, error: rows[provider]?.error ?? false },
            }));
          controllers.current.delete(controller);
          pending.current.delete(provider);
        }
      }

      const work = read();
      pending.current.set(provider, work);
      return work;
    },
    [client],
  );

  return { providers, providerError, catalogs, loadProviders, loadCatalog };
}
