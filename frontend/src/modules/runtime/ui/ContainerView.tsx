import feedbackStyles from '../../../shared/ui/Feedback.module.css';
import controlStyles from '../../../shared/ui/Controls.module.css';
import type { ReactNode } from 'react';
import { ArrowLeft, ArrowRight, Box, Cpu, LockKeyhole, RefreshCw, Terminal } from 'lucide-react';
import type { Container } from '../../../shared/contracts/contracts';
import type { Transport } from '../../../shared/contracts/transport';
import type { MessageKey } from '../../../shared/i18n/messages';
import { bytes, utc } from '../../../shared/lib/format';
import { useLocale } from '../../../shared/i18n/locale';
import { EnvironmentContent, LogContent } from './RuntimeContent';
import { HealthFact, Status } from '../../../shared/ui/ui';
import { Hint } from '../../../shared/ui/Hint';
import { useContainerRead, type RuntimeRead } from '../model/useContainerRead';
import widgetStyles from '../../../shared/ui/Widget.module.css';
import factStyles from '../../../shared/ui/FactStrip.module.css';
import styles from './ContainerView.module.css';

interface Props {
  client: Transport;
  container: Container;
  running: boolean;
  blockedReason?: MessageKey;
  automatic?: boolean;
  active?: boolean;
  back: () => void;
  diagnose: (container: Container) => void;
  continueDiagnosis?: (container: Container) => void;
}

/** Present current inspect data independently from manually read sources and diagnostic history. */
export function ContainerView({
  client,
  container,
  running,
  blockedReason,
  automatic = false,
  active = true,
  back,
  diagnose,
  continueDiagnosis,
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
  /** Render the current inspect facts and exact resource metadata. */
  function stateFacts() {
    return (
      state && (
        <>
          <div className={`${styles['runtime-state']} runtime-state`}>
            <Status state={state.state} />
            <code>{state.image}</code>
          </div>
          <HealthFact state={state.state} health={state.health} last_healthcheck={state.last_healthcheck} />
          <dl className={`${factStyles['fact-strip']} fact-strip ${styles['runtime-lifecycle']}`}>
            <div>
              <dt>{t('Exit code')}</dt>
              <dd
                className={
                  state.state === 'exited' && state.exit_code !== 0
                    ? `negative ${feedbackStyles['negative']}`
                    : undefined
                }
              >
                {state.exit_code}
              </dd>
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
          <dl className={`${styles['runtime-metadata']}`}>
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
      )
    );
  }

  /** Render the current bounded metrics snapshot. */
  function metricFacts() {
    return (
      measure && (
        <>
          <dl className={`${styles['runtime-metrics']}`}>
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
          <p className={`section-note ${controlStyles['section-note']}`}>{t('One measurement · no metric history')}</p>
        </>
      )
    );
  }

  /** Explain why either chat destination is temporarily unavailable. */
  function diagnosisReason(): MessageKey | undefined {
    if (running) return 'A request is running in the current chat.';
    if (blockedReason) return blockedReason;
    if (snapshot.missing) return 'This container no longer exists on the selected host.';
    if (snapshot.error) return 'Refresh container data before starting a diagnosis.';
    if (!state || snapshot.loading) return 'Refreshing container data…';
    return undefined;
  }

  /** Show explicit chat destinations and share one help trigger across unavailable actions. */
  function diagnosisActions() {
    const reason = diagnosisReason();
    const actions = (
      <span className={styles['diagnosis-actions']}>
        <button
          className={`primary ${controlStyles['primary']}`}
          disabled={Boolean(reason)}
          onClick={() => state && diagnose(state)}
        >
          {t(continueDiagnosis ? 'Diagnose in a new chat' : 'Diagnose')}
          <ArrowRight size={14} />
        </button>
        {continueDiagnosis && (
          <button
            className={`text-button ${controlStyles['text-button']} ${styles['continue-diagnosis']}`}
            disabled={Boolean(reason)}
            onClick={() => state && continueDiagnosis(state)}
          >
            {t('Continue in current chat')}
          </button>
        )}
      </span>
    );
    return (
      <div className={styles['diagnosis-controls']}>
        <Hint label={t('Why diagnosis is unavailable')} control={actions}>
          {reason ? t(reason) : undefined}
        </Hint>
      </div>
    );
  }

  /** Show the exact current target and its available controls. */
  function containerHeading() {
    return (
      <div className={`${styles['container-view-heading']}`}>
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
        <div className={`${styles['container-view-actions']}`}>
          <button
            className={`secondary ${controlStyles['secondary']}${fetching ? ` refreshing ${feedbackStyles['refreshing']}` : ''}`}
            onClick={refresh}
            disabled={loading}
            aria-busy={fetching}
          >
            <RefreshCw size={14} />
            {t('Refresh data')}
          </button>
          {diagnosisActions()}
        </div>
      </div>
    );
  }

  return (
    <section className={`${styles['container-view']}`} aria-label={t('Container facts')}>
      <div className={`${styles['container-view-nav']}`}>
        <button className={`text-button ${controlStyles['text-button']}`} onClick={back}>
          <ArrowLeft size={14} />
          {t('Back to investigation')}
        </button>
      </div>
      {containerHeading()}
      <p className={`${styles['runtime-feedback']}`} role="status" aria-live="polite">
        {t(
          loading
            ? 'Refreshing container data…'
            : automatic
              ? 'State refreshes every 10 seconds · logs and metrics refresh manually.'
              : 'Snapshot only · refresh manually for current data.',
        )}
      </p>
      {snapshot.missing && (
        <div className={`${styles['runtime-error']}`} role="alert">
          <p>{t('This container no longer exists on the selected host.')}</p>
          {state && <p>{t('Showing the last successful observation.')}</p>}
        </div>
      )}
      <div className={`${styles['container-view-grid']}`}>
        <div className={`${styles['container-view-column']}`}>
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
            {stateFacts()}
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
        <div className={`${styles['container-view-column']}`}>
          <ReadPanel
            title="Current metrics"
            source="Docker stats"
            icon={<Cpu size={16} />}
            read={metrics}
            error="Could not read container metrics."
            refresh={refresh}
            busy={loading}
          >
            {metricFacts()}
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
    <section
      className={`${widgetStyles.widget} widget ${styles['runtime-panel']}`}
      aria-label={t(title)}
      aria-busy={read.loading}
    >
      <header className={`${widgetStyles['widget-head']} widget-head`}>
        <h3>
          {icon}
          {t(title)}
        </h3>
        <span>{t(source)}</span>
      </header>
      {read.error && (
        <div className={`${styles['runtime-error']}`}>
          <p role="alert">{t(error)}</p>
          {read.data !== undefined && <p>{t('Showing the last successful observation.')}</p>}
          <button className={`text-button ${controlStyles['text-button']}`} onClick={refresh} disabled={busy}>
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
        <div className={`${styles['runtime-loading']}`} aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
      ) : null}
      {(observedAt || read.receivedAt) && (
        <footer className={`${widgetStyles['widget-foot']} widget-foot`}>
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
