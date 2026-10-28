import { ArrowRight, Check, Server } from 'lucide-react';
import type { Host } from './contracts';
import { useLocale } from './locale';
import { Modal } from './ui';

/** Select only configured hosts while leaving the current investigation intact until selection. */
export function HostPicker({
  hosts,
  host,
  loading,
  error,
  retry,
  choose,
  close,
  connect,
  returnFocusId,
}: {
  hosts: Host[];
  host: string;
  loading: boolean;
  error: string;
  retry: () => void;
  choose: (host: string) => void;
  close: () => void;
  connect: () => void;
  returnFocusId?: string;
}) {
  const { t } = useLocale();
  return (
    <Modal title={t('Choose a host')} close={close} returnFocusId={returnFocusId}>
      <p className="host-picker-description">
        {t('Choose a configured Docker host. Selecting another host starts a separate session.')}
      </p>
      {loading && <p role="status">{t('Loading hosts…')}</p>}
      {error && (
        <div className="turn-error">
          <p role="alert">{error}</p>
          <button className="secondary" onClick={retry} disabled={loading}>
            {t('Retry hosts')}
          </button>
        </div>
      )}
      <div className="host-picker-list">
        {hosts.map((row) => (
          <button
            className="host-picker-row"
            key={row.id}
            aria-pressed={row.id === host}
            onClick={() => choose(row.id)}
            disabled={loading}
          >
            <Server size={18} />
            <span>
              <strong>{row.name}</strong>
              <code>{row.id}</code>
            </span>
            {row.id === host ? (
              <span className="host-current">
                {t('Current host')}
                <Check size={15} />
              </span>
            ) : (
              <ArrowRight size={16} />
            )}
          </button>
        ))}
        {!hosts.length && !loading && !error && <p className="empty-note">{t('No configured hosts')}</p>}
      </div>
      <button className="text-button host-picker-connect" onClick={connect}>
        {t('Change connection')}
        <ArrowRight size={14} />
      </button>
    </Modal>
  );
}
