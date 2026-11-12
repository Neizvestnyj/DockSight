import sharedStyles from '../../../shared/ui/Shared.module.css';
import controlStyles from '../../../shared/ui/Controls.module.css';
import { useState } from 'react';
import { RefreshCw, Trash2 } from 'lucide-react';
import { useLocale } from '../../../shared/i18n/locale';
import { Modal } from '../../../shared/ui/ui';
import { utc } from '../../../shared/lib/format';
import type { InvestigationSummary } from '../../../shared/contracts/investigation-contracts';
import styles from './SavedInvestigations.module.css';
import modalStyles from '../../../shared/ui/Modal.module.css';

interface Props {
  items: InvestigationSummary[];
  selected?: string;
  loading: boolean;
  error: string;
  nextCursor: string | null;
  open: (id: string) => void;
  older: () => void;
  refresh: () => void;
  remove: (id: string) => void;
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
}: Props) {
  const { t } = useLocale();
  const [deleting, setDeleting] = useState<InvestigationSummary | null>(null);
  return (
    <section className={`${styles['saved-investigations']}`} aria-label={t('Saved chats')} aria-busy={loading}>
      <header>
        <h2>{t('Saved chats')}</h2>
        <button
          className={`icon-button ${controlStyles['icon-button']}`}
          aria-label={t('Refresh saved chats')}
          disabled={loading}
          onClick={refresh}
        >
          <RefreshCw size={14} />
        </button>
      </header>
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
