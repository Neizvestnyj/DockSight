import {
  useCallback,
  useEffect,
  useEffectEvent,
  useRef,
  useState,
  type ReactNode,
  type Ref,
  type RefObject,
} from 'react';
import { X } from 'lucide-react';
import type { SearchPage } from '../contracts/search-contracts';
import { useLocale } from '../i18n/locale';
import type { MessageKey } from '../i18n/messages';
import controlStyles from './Controls.module.css';
import styles from './ListSearch.module.css';

interface Props<Row> {
  label: MessageKey;
  empty: MessageKey;
  load: (query: string, signal: AbortSignal, before?: string) => Promise<SearchPage<Row>>;
  row: (item: Row) => ReactNode;
  close: () => void;
  trigger?: RefObject<HTMLButtonElement | null>;
  browsing?: ReactNode;
  scope?: string;
  maxLength?: number;
  onQueryChange?: () => void;
  resultsClassName?: string;
}

/** Search the list in place while keeping navigation and inventory state independent. */
export function ListSearch<Row>({
  label,
  empty,
  load,
  row,
  close,
  trigger,
  browsing,
  scope,
  maxLength = 128,
  onQueryChange,
  resultsClassName,
}: Props<Row>) {
  const { t } = useLocale();
  const [input, setInput] = useState('');
  const [page, setPage] = useState<SearchPage<Row>>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const panel = useRef<HTMLDivElement>(null);
  const field = useRef<HTMLInputElement>(null);
  const results = useRef<HTMLDivElement>(null);
  const continuation = useRef<HTMLButtonElement>(null);
  const active = useRef<AbortController | null>(null);
  const query = input.trim();

  const read = useCallback(
    async (value: string, before?: string) => {
      if (active.current) return;
      const controller = new AbortController();
      active.current = controller;
      setLoading(true);
      setError(false);
      try {
        const next = await load(value, controller.signal, before);
        if (!controller.signal.aborted) {
          if (before && !next.next_cursor && document.activeElement === continuation.current)
            results.current?.focus({ preventScroll: true });
          setPage((previous) => ({
            ...next,
            items: before && previous ? [...previous.items, ...next.items] : next.items,
          }));
        }
      } catch {
        if (!controller.signal.aborted) setError(true);
      } finally {
        if (active.current === controller) {
          active.current = null;
          setLoading(false);
        }
      }
    },
    [load],
  );

  useEffect(() => field.current?.focus(), []);
  const dismiss = useEffectEvent((event: MouseEvent) => {
    const path = event.composedPath();
    const toggle = trigger?.current;
    if (!panel.current || path.includes(panel.current) || (toggle && path.includes(toggle))) return;
    close();
  });
  useEffect(() => {
    const handleClick = (event: MouseEvent) => dismiss(event);
    document.addEventListener('click', handleClick);
    return () => document.removeEventListener('click', handleClick);
  }, []);

  useEffect(() => {
    if (!query) return;
    const timer = setTimeout(() => void read(query), 250);
    return () => {
      clearTimeout(timer);
      active.current?.abort();
      active.current = null;
    };
  }, [query, read]);

  function change(value: string) {
    if (value.trim() !== query) {
      active.current?.abort();
      active.current = null;
      setPage(undefined);
      setLoading(false);
      setError(false);
      onQueryChange?.();
    }
    setInput(value);
  }

  return (
    <div ref={panel} className={styles.search}>
      <div className={styles.field}>
        <input
          ref={field}
          type="search"
          value={input}
          aria-label={t(label)}
          placeholder={t(label)}
          maxLength={maxLength}
          onChange={(event) => change(event.currentTarget.value)}
          onKeyDown={(event) => {
            if (event.key !== 'Escape') return;
            event.preventDefault();
            event.stopPropagation();
            close();
            trigger?.current?.focus();
          }}
        />
        {input && (
          <button
            type="button"
            className={controlStyles['icon-button']}
            aria-label={t('Clear search')}
            onClick={() => {
              change('');
              field.current?.focus();
            }}
          >
            <X size={14} aria-hidden="true" />
          </button>
        )}
      </div>
      {scope && <p className={controlStyles['section-note']}>{t('Search scope: {scope}', { scope })}</p>}
      {query ? (
        <>
          <div
            ref={results}
            tabIndex={-1}
            className={resultsClassName ? `${styles.results} ${resultsClassName}` : styles.results}
            aria-busy={loading}
          >
            {page?.items.map(row)}
            {page && !page.items.length && (
              <p role="status" className={controlStyles['section-note']}>
                {t(empty)}
              </p>
            )}
          </div>
          {error ? (
            <div className={styles.feedback}>
              <p role="alert">{t('Could not load search results.')}</p>
              <button
                className={controlStyles['text-button']}
                onClick={() => void read(query, page?.next_cursor ?? undefined)}
              >
                {t('Retry')}
              </button>
            </div>
          ) : (
            <SearchContinuation
              loading={loading || !page}
              more={page?.next_cursor}
              trigger={continuation}
              read={(before) => void read(query, before)}
            />
          )}
        </>
      ) : (
        browsing
      )}
    </div>
  );
}

/** Keep loading and continuation controls under the results they belong to. */
function SearchContinuation({
  loading,
  more,
  trigger,
  read,
}: {
  loading: boolean;
  more?: string | null;
  trigger: Ref<HTMLButtonElement>;
  read: (before: string) => void;
}) {
  const { t } = useLocale();
  return (
    <>
      {more && (
        <button
          ref={trigger}
          aria-disabled={loading}
          className={controlStyles['text-button']}
          onClick={() => read(more)}
        >
          {t('More results')}
        </button>
      )}
      {loading && (
        <p role="status" className={controlStyles['section-note']}>
          {t('Searching…')}
        </p>
      )}
    </>
  );
}
