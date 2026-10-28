import type { ReactNode } from 'react';
import { ArrowLeft, ArrowRight, Box, Cpu, LockKeyhole, RefreshCw, Terminal } from 'lucide-react';
import type { Container, Transport } from './contracts';
import type { MessageKey } from './messages';
import { bytes, utc } from './format';
import { useLocale } from './locale';
import { EnvironmentContent, LogContent } from './RuntimeContent';
import { Status } from './ui';
import { useContainerRead, type RuntimeRead } from './useContainerRead';

interface Props {
  client: Transport;
  container: Container;
  running: boolean;
  blocked?: boolean;
  automatic?: boolean;
  active?: boolean;
  back: () => void;
  diagnose: (container: Container) => void;
}

/** Present current inspect data independently from manually read sources and diagnostic history. */
export function ContainerView({
  client,
  container,
  running,
  blocked = false,
  automatic = false,
  active = true,
  back,
  diagnose,
}: Props) {
  const { t, locale } = useLocale();
  const { snapshot, logs, metrics, refresh, loading, fetching } = useContainerRead(
    client,
    container.host,
    container.id,
    automatic,
    active,
  );
  const state = snapshot.data;
  const measure = metrics.data;
  return (
    <section className="container-view" aria-label={t('Container facts')}>
      <div className="container-view-nav">
        <button className="text-button" onClick={back}>
          <ArrowLeft size={14} />
          {t('Back to investigation')}
        </button>
      </div>
      <div className="container-view-heading">
        <div>
          <h2 id="container-title" tabIndex={-1}>
            {state?.name ?? container.name}
          </h2>
          <p>
            <span>{container.host}</span>
            <span> · </span>
            <code>{container.id}</code>
          </p>
        </div>
        <div className="container-view-actions">
          <button
            className={`secondary${fetching ? ' refreshing' : ''}`}
            onClick={refresh}
            disabled={loading}
            aria-busy={fetching}
          >
            <RefreshCw size={14} />
            {t('Refresh data')}
          </button>
          <button
            className="primary"
            disabled={running || blocked || !state || snapshot.loading || Boolean(snapshot.error)}
            onClick={() => state && diagnose(state)}
          >
            {t('Diagnose')}
            <ArrowRight size={14} />
          </button>
        </div>
      </div>
      <p className="runtime-feedback" role="status" aria-live="polite">
        {t(
          loading
            ? 'Refreshing container data…'
            : automatic
              ? 'State refreshes every 10 seconds · logs and metrics refresh manually.'
              : 'Snapshot only · refresh manually for current data.',
        )}
      </p>
      {snapshot.missing && (
        <div className="runtime-error" role="alert">
          <p>{t('This container no longer exists on the selected host.')}</p>
          {state && <p>{t('Showing the last successful observation.')}</p>}
        </div>
      )}
      <div className="container-view-grid">
        <div className="container-view-column">
          <ReadPanel
            title="Container status"
            source="Docker inspect"
            icon={<Box size={16} />}
            read={snapshot}
            error="Could not read container state."
            refresh={refresh}
            busy={loading}
            observedAt={state?.observed_at}
          >
            {state && (
              <>
                <div className="runtime-state">
                  <Status state={state.state} />
                  <code>{state.image}</code>
                </div>
                <dl className="fact-strip runtime-lifecycle">
                  <div>
                    <dt>{t('Exit code')}</dt>
                    <dd>{state.exit_code}</dd>
                  </div>
                  <div>
                    <dt>{t('OOM killed')}</dt>
                    <dd>{t(state.oom_killed ? 'Yes' : 'No')}</dd>
                  </div>
                  <div>
                    <dt>{t('Restarts')}</dt>
                    <dd>{state.restart_count}</dd>
                  </div>
                </dl>
                <dl className="runtime-metadata">
                  <div>
                    <dt>{t('Started')}</dt>
                    <dd>
                      {state.started_at ? (
                        <time dateTime={state.started_at}>{timestamp(state.started_at)}</time>
                      ) : (
                        t('Unavailable')
                      )}
                    </dd>
                  </div>
                  <div>
                    <dt>{t('Compose project')}</dt>
                    <dd>{state.compose_project ?? t('None reported')}</dd>
                  </div>
                </dl>
              </>
            )}
          </ReadPanel>
          <ReadPanel
            title="Container logs"
            source="Docker logs"
            icon={<Terminal size={16} />}
            read={logs}
            error="Could not read container logs."
            refresh={refresh}
            busy={loading}
          >
            {logs.data && <LogContent logs={logs.data} />}
          </ReadPanel>
        </div>
        <div className="container-view-column">
          <ReadPanel
            title="Current metrics"
            source="Docker stats"
            icon={<Cpu size={16} />}
            read={metrics}
            error="Could not read container metrics."
            refresh={refresh}
            busy={loading}
          >
            {measure && (
              <>
                <dl className="runtime-metrics">
                  <div>
                    <dt>{t('CPU')}</dt>
                    <dd className={measure.cpu_percent === null ? 'unavailable' : ''}>
                      {measure.cpu_percent === null
                        ? t('Unavailable')
                        : `${measure.cpu_percent.toLocaleString(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`}
                    </dd>
                  </div>
                  <div>
                    <dt>{t('Memory usage')}</dt>
                    <dd className={measure.memory_usage_bytes === null ? 'unavailable' : ''}>
                      {bytes(measure.memory_usage_bytes, locale, t('Unavailable'))}
                    </dd>
                  </div>
                  <div>
                    <dt>{t('Memory limit')}</dt>
                    <dd className={measure.memory_limit_bytes === null ? 'unavailable' : ''}>
                      {bytes(measure.memory_limit_bytes, locale, t('Unavailable'))}
                    </dd>
                  </div>
                </dl>
                <p className="section-note">{t('One measurement · no metric history')}</p>
              </>
            )}
          </ReadPanel>
          <ReadPanel
            title="Environment"
            source="Docker inspect"
            icon={<LockKeyhole size={16} />}
            read={snapshot}
            error="Could not read allowlisted environment."
            refresh={refresh}
            busy={loading}
            observedAt={state?.observed_at}
          >
            {state && <EnvironmentContent variables={Object.fromEntries(state.environment)} />}
          </ReadPanel>
        </div>
      </div>
    </section>
  );
}

/** Keep failures local to their source, with the last successful values and their original timestamps. */
function ReadPanel({
  title,
  source,
  icon,
  read,
  error,
  refresh,
  busy,
  observedAt,
  children,
}: {
  title: MessageKey;
  source: MessageKey;
  icon: ReactNode;
  read: RuntimeRead<unknown>;
  error: MessageKey;
  refresh: () => void;
  busy: boolean;
  observedAt?: string;
  children: ReactNode;
}) {
  const { t } = useLocale();
  return (
    <section className="widget runtime-panel" aria-label={t(title)} aria-busy={read.loading}>
      <header className="widget-head">
        <h3>
          {icon}
          {t(title)}
        </h3>
        <span>{t(source)}</span>
      </header>
      {read.error && (
        <div className="runtime-error">
          <p role="alert">{t(error)}</p>
          {read.data !== undefined && <p>{t('Showing the last successful observation.')}</p>}
          <button className="text-button" onClick={refresh} disabled={busy}>
            {t('Retry data')}
            <ArrowRight size={13} />
          </button>
          <details>
            <summary>{t('Technical details')}</summary>
            <p>{read.error}</p>
          </details>
        </div>
      )}
      {read.data !== undefined ? (
        children
      ) : read.loading ? (
        <div className="runtime-loading" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
      ) : null}
      {(observedAt || read.receivedAt) && (
        <footer className="widget-foot">
          <span>{t(observedAt ? 'Observed' : 'Received')}</span>
          <time dateTime={observedAt ?? read.receivedAt}>{timestamp((observedAt ?? read.receivedAt)!)}</time>
        </footer>
      )}
    </section>
  );
}

/** Show the full UTC date so a retained observation is not mistaken for today's reading. */
function timestamp(value: string): string {
  return `${new Date(value).toISOString().slice(0, 10)} · ${utc(value)}`;
}
