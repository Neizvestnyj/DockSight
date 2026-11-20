import sharedStyles from '../../../shared/ui/Shared.module.css';
import controlStyles from '../../../shared/ui/Controls.module.css';
import { useCallback, useRef, useState, type ReactNode } from 'react';
import { RefreshCw, Search, Trash2 } from 'lucide-react';
import { useLocale } from '../../../shared/i18n/locale';
import { Modal } from '../../../shared/ui/ui';
import { utc } from '../../../shared/lib/format';
import type { HistoryTransport, InvestigationSummary } from '../../../shared/contracts/investigation-contracts';
import type { ChatSearchResult } from '../../../shared/contracts/search-contracts';
import { ListSearch } from '../../../shared/ui/ListSearch';
import styles from './SavedInvestigations.module.css';
import modalStyles from '../../../shared/ui/Modal.module.css';

interface Props {
  items: InvestigationSummary[];
  selected?: string;
  loading: boolean;
  error: string;
  nextCursor: string | null;
  open: (id: string, turnId?: string | null) => void;
  searchHistory?: HistoryTransport;
  older: () => void;
  refresh: () => void;
  remove: (id: string) => void;
}

/** Offer retained tab-local Demo chats without presenting them as saved API history. */
export function DemoInvestigations({
  items,
  running,
  open,
}: {
  items: { id: string; title?: string }[];
  running: boolean;
  open: (id: string) => void;
}) {
  const { t } = useLocale();
  if (!items.length) return null;
  return (
    <section className={styles['saved-investigations']} aria-label={t('Demo chats')}>
      <header>
        <h2>{t('Demo chats')}</h2>
      </header>
      <div className={styles['saved-chat-list']}>
        {items.map(({ id, title }) => (
          <div className={styles['saved-chat']} key={id}>
            <button className={styles['saved-chat-open']} disabled={running} onClick={() => open(id)}>
              <span>{title || t('Untitled chat')}</span>
            </button>
          </div>
        ))}
      </div>
    </section>
  );
}

/** Keep saved-chat navigation compact beside the existing host and inventory controls. */
export function SavedInvestigations({
  items,
  selected,
  loading,
  error,
  nextCursor,
  open,
  older,
  refresh,
  remove,
  searchHistory,
}: Props) {
  const { t } = useLocale();
  const [deleting, setDeleting] = useState<InvestigationSummary | null>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const searchTrigger = useRef<HTMLButtonElement>(null);

  function browsing() {
    return (
      <>
        {loading && !items.length && (
          <p className={`section-note ${controlStyles['section-note']}`}>{t('Loading saved chats…')}</p>
        )}
        {!loading && !items.length && !error && (
          <p className={`section-note ${controlStyles['section-note']}`}>{t('No saved chats yet.')}</p>
        )}
        <div className={`${styles['saved-chat-list']}`}>
          {items.map((row) => (
            <div className={`${styles['saved-chat']} saved-chat${selected === row.id ? ' selected' : ''}`} key={row.id}>
              <button
                className={`${styles['saved-chat-open']}`}
                aria-current={selected === row.id ? 'page' : undefined}
                onClick={() => open(row.id)}
                title={`${row.title || t('Untitled chat')} · ${utc(row.updated_at, true)}`}
              >
                <span>{row.title || t('Untitled chat')}</span>
                <small>
                  {row.host} · <time dateTime={row.updated_at}>{utc(row.updated_at, true)}</time>
                </small>
              </button>
              <button
                className={`icon-button ${controlStyles['icon-button']}`}
                aria-label={t('Delete saved chat: {title}', { title: row.title || t('Untitled chat') })}
                onClick={() => setDeleting(row)}
                disabled={Boolean(row.active_turn_id)}
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))}
        </div>
        {error && (
          <div className={`sidebar-error ${sharedStyles['sidebar-error']}`}>
            <p role="alert">
              {t(
                error === 'Could not load saved chats.'
                  ? error
                  : 'Could not delete chat. Running diagnoses must finish or be stopped first.',
              )}
            </p>
            <button className={`text-button ${controlStyles['text-button']}`} onClick={refresh}>
              {t('Retry')}
            </button>
          </div>
        )}
        {nextCursor && (
          <button className={`text-button ${controlStyles['text-button']}`} disabled={loading} onClick={older}>
            {t('Older chats')}
          </button>
        )}
      </>
    );
  }

  return (
    <section className={styles['saved-investigations']} aria-label={t('Saved chats')} aria-busy={loading}>
      <header>
        <h2>{t('Saved chats')}</h2>
        {searchHistory && (
          <button
            ref={searchTrigger}
            type="button"
            className={controlStyles['icon-button']}
            aria-label={t('Search chats')}
            aria-expanded={searchOpen}
            onClick={() => setSearchOpen((value) => !value)}
          >
            <Search size={14} aria-hidden="true" />
          </button>
        )}
        <button
          className={`icon-button ${controlStyles['icon-button']}`}
          aria-label={t('Refresh saved chats')}
          disabled={loading}
          onClick={refresh}
        >
          <RefreshCw size={14} />
        </button>
      </header>
      {searchOpen && searchHistory ? (
        <SavedChatSearch
          history={searchHistory}
          selected={selected}
          open={open}
          close={() => {
            setSearchOpen(false);
            searchTrigger.current?.focus();
          }}
          browsing={browsing()}
        />
      ) : (
        browsing()
      )}
      {deleting && (
        <Modal title={t('Delete saved chat')} close={() => setDeleting(null)}>
          <p>{t('Delete “{title}” and its saved answers?', { title: deleting.title || t('Untitled chat') })}</p>
          <p className={`section-note ${controlStyles['section-note']}`}>
            {t('This cannot be undone. Existing action protection remains on the server.')}
          </p>
          <footer className={`${modalStyles['modal-actions']} modal-actions`}>
            <button className={`secondary ${controlStyles['secondary']}`} onClick={() => setDeleting(null)}>
              {t('Cancel')}
            </button>
            <button
              className={`primary ${controlStyles['primary']}`}
              onClick={() => {
                remove(deleting.id);
                setDeleting(null);
              }}
            >
              {t('Delete chat')}
            </button>
          </footer>
        </Modal>
      )}
    </section>
  );
}

/** Open one matched question through the regular owned-chat navigation. */
function SavedChatSearch({
  history,
  selected,
  open,
  close,
  browsing,
}: {
  history: HistoryTransport;
  selected?: string;
  open: Props['open'];
  close: () => void;
  browsing: ReactNode;
}) {
  const { t } = useLocale();
  const load = useCallback(
    (query: string, signal: AbortSignal, before?: string) => history.searchInvestigations(query, signal, before),
    [history],
  );

  function result({ id, title, host, updated_at, match }: ChatSearchResult) {
    return (
      <button
        key={id}
        className={styles['search-result']}
        type="button"
        aria-current={selected === id ? 'page' : undefined}
        onClick={() => open(id, match?.turn_id ?? null)}
      >
        <span>{title || t('Untitled chat')}</span>
        {match && (
          <small className={styles.excerpt}>
            {match.excerpt.slice(0, match.start)}
            <mark>{match.excerpt.slice(match.start, match.end)}</mark>
            {match.excerpt.slice(match.end)}
          </small>
        )}
        <small>
          {host} · <time dateTime={updated_at}>{utc(updated_at, true)}</time>
        </small>
      </button>
    );
  }

  return (
    <ListSearch
      label="Search chats"
      empty="No matching chats."
      load={load}
      row={result}
      close={close}
      browsing={browsing}
      maxLength={120}
      resultsClassName={styles['saved-chat-list']}
    />
  );
}
