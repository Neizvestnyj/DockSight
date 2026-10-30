import type { LogBatch } from './contracts';
import { useLocale } from './locale';
import { utc } from './format';

/** Render sanitized log strings verbatim in both historical cards and direct Docker reads. */
export function LogContent({ logs, grouped = false }: { logs: LogBatch; grouped?: boolean }) {
  const { t } = useLocale();
  const first = logs.entries[0]?.timestamp;
  const last = logs.entries.at(-1)?.timestamp;
  return (
    <>
      <div className="log-toolbar">
        <span>{t('{count} lines returned', { count: logs.entries.length })}</span>
        <span>{t(logs.truncated ? 'Truncated · partial evidence' : 'Within requested bounds')}</span>
      </div>
      {!!logs.entries.length && (
        <div className="log-window">
          <span>{t('Latest log window · oldest first')}</span>
          {first && last && (
            <span className="log-window-range">
              <time dateTime={first}>{utc(first, true)}</time>
              <span aria-hidden="true">→</span>
              <time dateTime={last}>{utc(last, true)}</time>
            </span>
          )}
        </div>
      )}
      <div
        className="logs"
        tabIndex={0}
        role={grouped ? 'group' : 'region'}
        aria-label={t('Timestamped container logs')}
      >
        {logs.entries.length ? (
          logs.entries.map((entry, index) => (
            <div className="log-line" key={index}>
              <time
                dateTime={entry.timestamp ?? undefined}
                title={entry.timestamp ? utc(entry.timestamp, true) : undefined}
              >
                {entry.timestamp ? utc(entry.timestamp).replace(' UTC', '') : t('No time')}
              </time>
              <code>{entry.message}</code>
            </div>
          ))
        ) : (
          <p>
            {t(
              logs.truncated
                ? 'No complete log lines fit within the limit. The log is incomplete.'
                : 'No log entries returned. An empty log does not establish the cause.',
            )}
          </p>
        )}
      </div>
    </>
  );
}

/** Display only the environment values allowlisted by the backend, with no HTML interpretation. */
export function EnvironmentContent({ variables }: { variables: Record<string, string> }) {
  const { t } = useLocale();
  return (
    <>
      <p className="section-note">{t('Allowlisted variables · read only')}</p>
      <dl className="env-list">
        {Object.keys(variables).length ? (
          Object.entries(variables).map(([key, value]) => (
            <div key={key}>
              <dt>
                <code>{key}</code>
              </dt>
              <dd>
                <code>{value}</code>
              </dd>
            </div>
          ))
        ) : (
          <div>
            <dt>{t('No allowlisted variables returned.')}</dt>
          </div>
        )}
      </dl>
    </>
  );
}
