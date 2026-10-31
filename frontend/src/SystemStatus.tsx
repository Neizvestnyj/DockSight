import { Activity, LoaderCircle, RefreshCw, ArrowRight } from 'lucide-react';
import type { CheckState, DependencyCheck } from './contracts';
import { utc } from './format';
import { useLocale } from './locale';
import type { MessageKey } from './messages';
import { Modal } from './ui';
import { checkReasons, type useSystemStatus } from './useSystemStatus';

type Availability = ReturnType<typeof useSystemStatus>;
const labels: Record<CheckState, MessageKey> = {
  available: 'Available',
  unavailable: 'Unavailable',
  not_checked: 'Not checked',
};

/** Keep three dependency signals compact while leaving complete results one keyboard action away. */
export function SystemStatusTrigger({ status, open }: { status: Availability; open: () => void }) {
  const { t } = useLocale();
  const rows = [
    ['API', status.api.state],
    ['Docker', status.data?.docker.state ?? 'not_checked'],
  ] as const;
  const worst = rows.some(([, state]) => state === 'unavailable')
    ? 'unavailable'
    : rows.every(([, state]) => state === 'available')
      ? 'available'
      : 'not_checked';
  const summary = rows.map(([name, state]) => `${t(name)}: ${t(labels[state])}`).join(' · ');
  return (
    <button
      className="system-status-trigger"
      id="system-status-trigger"
      title={`${t('System status')}: ${summary}`}
      aria-description={summary}
      aria-haspopup="dialog"
      aria-busy={status.loading}
      onClick={open}
    >
      <span className="sr-only">{t('System status')}</span>
      {status.loading ? <LoaderCircle size={16} className="spin" /> : <Activity size={16} />}
      <span className={`check-dot check-${worst} system-status-compact`} aria-hidden="true" />
      <span className="system-status-signals">
        {rows.map(([name, state]) => (
          <span key={name}>
            <span className={`check-dot check-${state}`} />
            {t(name)}{' '}
          </span>
        ))}
      </span>
    </button>
  );
}

/** Explain metadata availability, freshness, and limitations without offering server configuration edits. */
export function SystemStatusPanel({
  status,
  host,
  demo,
  close,
  connect,
}: {
  status: Availability;
  host: string;
  demo: boolean;
  close: () => void;
  connect: () => void;
}) {
  const { t } = useLocale();
  const data = status.data;
  const feedback: MessageKey = status.stopped
    ? 'Automatic checks stopped. Retry manually.'
    : status.automatic
      ? status.blockedReason
        ? 'Automatic checks retry with increasing intervals.'
        : 'Checks refresh every minute while this tab is visible.'
      : 'No background polling';
  const providerNames = {
    ollama: 'Ollama',
    openai: 'OpenAI',
    anthropic: 'Anthropic',
    gemini: 'Gemini',
    compatible: 'OpenAI-compatible',
  } as const;
  const dependency = (check?: DependencyCheck) => ({
    state: check?.state ?? ('not_checked' as CheckState),
    reason: check ? checkReasons[check.code] : ('Not checked' as MessageKey),
    checkedAt: check?.checked_at,
  });
  const rows = [
    { name: 'API & authorization' as const, ...status.api },
    { name: 'Docker' as const, ...dependency(data?.docker) },
    { name: 'Provider' as const, ...dependency(data?.provider_check) },
    { name: 'Model' as const, ...dependency(data?.model_check) },
  ];
  return (
    <Modal title={t('System status')} close={close} returnFocusId="system-status-trigger">
      <div className="system-status-scope">
        <div>
          <span>{t('Host')}</span>
          <strong>{host || t('No host selected')}</strong>
        </div>
        <div>
          <span>{t('Provider & model')}</span>
          <strong>
            {data ? (
              <>
                {providerNames[data.provider]} · <code>{data.model}</code>
              </>
            ) : (
              t('Not checked')
            )}
          </strong>
        </div>
      </div>
      {demo && <p className="status-demo-note">{t('Demo statuses are simulated. No connections are checked.')}</p>}
      {data && status.api.state !== 'available' && (
        <p className="status-stale-note">{t('Dependency results are from the previous successful check.')}</p>
      )}
      <div className="system-checks" aria-busy={status.loading}>
        {rows.map((row) => (
          <section className="system-check" aria-label={t(row.name)} key={row.name}>
            <div className="system-check-heading">
              <h3>{t(row.name)}</h3>
              <span className={`check-label check-${row.state}`}>
                <span className="check-dot" />
                {t(labels[row.state])}
              </span>
            </div>
            <p>{t(row.reason)}</p>
            {row.checkedAt && (
              <time dateTime={row.checkedAt}>
                {new Date(row.checkedAt).toISOString().slice(0, 10)} · {utc(row.checkedAt)}
              </time>
            )}
          </section>
        ))}
      </div>
      <p className="status-limit">
        {t('Tools and structured output have not been tested.')}{' '}
        {t('This check reads metadata only and never generates an answer.')}
      </p>
      <p className="section-note">{t('Provider and model settings are managed on the server.')}</p>
      <footer className="modal-actions status-actions">
        <span className="status-check-feedback" role="status">
          {status.loading ? t('Checking dependencies…') : t(feedback)}
        </span>
        {status.api.state === 'unavailable' && !demo && (
          <button className="text-button" onClick={connect}>
            {t('Change connection')}
            <ArrowRight size={14} />
          </button>
        )}
        <button
          className="primary"
          disabled={status.loading && (status.interactive || !status.api.checkedAt)}
          onClick={status.refresh}
        >
          <RefreshCw size={14} className={status.loading ? 'spin' : undefined} />
          {t('Check again')}
        </button>
      </footer>
    </Modal>
  );
}
