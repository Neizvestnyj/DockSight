import controlStyles from '../../../shared/ui/Controls.module.css';
import { ArrowRight, ArrowUpRight, Server } from 'lucide-react';
import {
  targetKey,
  type DiagnosticTarget,
  type Evidence,
  type HostOverview as Overview,
} from '../../../shared/contracts/contracts';
import { utc } from '../../../shared/lib/format';
import { useLocale } from '../../../shared/i18n/locale';
import { targetKindLabel } from '../../../shared/i18n/messages';
import { ContainerStatus } from '../../../shared/ui/ui';
import styles from './HostOverview.module.css';

/** Render bounded local observations and offer explicit, separate investigations of observed targets. */
export function HostOverview({
  report,
  evidence,
  inspect,
  narrow,
  disabled,
}: {
  report: Overview;
  evidence: Evidence[];
  inspect: (id: string) => void;
  narrow: (target: DiagnosticTarget) => void;
  disabled: boolean;
}) {
  const { t, locale } = useLocale();
  const source = evidence.find((row) => row.id === report.evidence_id);
  return (
    <section className={`${styles['host-overview']}`} aria-label={t('Host overview')}>
      <header className={`${styles['host-overview-heading']}`}>
        <Server size={18} aria-hidden="true" />
        <div>
          <h2>{t('Host overview')}</h2>
          <span className={`section-note ${controlStyles['section-note']}`}>{report.host}</span>
        </div>
        <button
          className={`evidence-link ${controlStyles['evidence-link']}`}
          type="button"
          onClick={() => inspect(report.evidence_id)}
        >
          {t('Source')}
          <ArrowUpRight size={13} aria-hidden="true" />
        </button>
      </header>
      <dl className={`${styles['host-overview-totals']}`}>
        <div>
          <dt>{t('Observed containers')}</dt>
          <dd>{report.total.toLocaleString(locale)}</dd>
        </div>
        <div>
          <dt>{t('running')}</dt>
          <dd>{report.running.toLocaleString(locale)}</dd>
        </div>
        <div>
          <dt>{t('Needs review')}</dt>
          <dd className={report.attention ? `warning-text ${controlStyles['warning-text']}` : ''}>
            {report.attention.toLocaleString(locale)}
          </dd>
        </div>
      </dl>
      <p className={`${styles['host-overview-note']}`}>
        {t('Local Docker containers only. Remote Swarm replicas are not included.')}
      </p>
      {report.truncated && (
        <p className={`${styles['host-overview-note']} warning-text ${controlStyles['warning-text']}`}>
          {t('Observation limits reached. More containers or group choices may exist.')}
        </p>
      )}
      {report.discovery_code && (
        <p className={`${styles['host-overview-note']} warning-text ${controlStyles['warning-text']}`}>
          {t('Group discovery is incomplete. Local container observations are retained.')}{' '}
          <code>{report.discovery_code}</code>
        </p>
      )}
      <div className={`${styles['host-members']}`}>
        {report.members.map((row) => {
          const log = report.logs.find((item) => item.container_id === row.container_id);
          return (
            <article className={`${styles['host-member']}`} key={row.container_id} aria-label={row.name}>
              <div className={`${styles['host-member-name']}`}>
                <h3 title={row.name}>{row.name}</h3>
                <span className={`mono section-note ${controlStyles['section-note']}`} title={row.container_id}>
                  {row.container_id.slice(0, 12)}
                </span>
                <span className={`section-note ${controlStyles['section-note']}`}>
                  {row.group ? `${targetKindLabel(row.group.kind, t)} / ${row.group.name}` : t('No observed group')}
                </span>
              </div>
              <div className={`${styles['host-member-state']}`}>
                <ContainerStatus state={row.state} health={row.health} last_healthcheck={row.last_healthcheck} />
                <span className={`section-note ${controlStyles['section-note']}`}>
                  {t('Exit code')} {row.exit_code} · {t('Restarts')} {row.restart_count.toLocaleString(locale)}
                  {row.oom_killed ? ` · ${t('OOM killed')}` : ''}
                </span>
                {row.attention && (
                  <span
                    className={`section-note ${controlStyles['section-note']} warning-text ${controlStyles['warning-text']}`}
                  >
                    {t('Needs review')}
                  </span>
                )}
              </div>
              <div className={`${styles['host-member-coverage']}`}>
                {log?.state === 'collected' && log.evidence_id ? (
                  <button
                    type="button"
                    className={`evidence-link ${controlStyles['evidence-link']}`}
                    onClick={() => inspect(log.evidence_id!)}
                  >
                    {t('Logs')}
                    <ArrowUpRight size={13} aria-hidden="true" />
                  </button>
                ) : (
                  <span
                    className={`section-note ${controlStyles['section-note']}${row.attention ? ` warning-text ${controlStyles['warning-text']}` : ''}`}
                  >
                    {t(log?.state === 'failed' ? 'Log read failed' : 'Logs not collected')}
                    {log?.code && (
                      <small>
                        {log.code === 'host_log_limit' ? t('Collection limit reached') : <code>{log.code}</code>}
                      </small>
                    )}
                  </span>
                )}
                <time className={`section-note ${controlStyles['section-note']}`} dateTime={row.observed_at}>
                  {utc(row.observed_at)}
                </time>
                <button
                  type="button"
                  className={`text-button ${controlStyles['text-button']}`}
                  disabled={disabled}
                  onClick={() => narrow({ kind: 'container', id: row.container_id, name: row.name })}
                >
                  {t('Investigate container')}
                  <ArrowRight size={13} aria-hidden="true" />
                </button>
              </div>
            </article>
          );
        })}
        {!report.members.length && (
          <p className={`empty-note ${controlStyles['empty-note']}`}>
            {t(report.total ? 'Container preview omitted by collection limits.' : 'No containers in this observation.')}
          </p>
        )}
      </div>
      {report.targets.length > 0 && (
        <div className={`${styles['host-overview-targets']}`}>
          <h3>{t('Narrow to an observed group')}</h3>
          <p className={`section-note ${controlStyles['section-note']}`}>
            {t('Starts a new investigation. Your draft is preserved.')}
          </p>
          <div>
            {report.targets.map((target) => (
              <button
                type="button"
                className={`secondary ${controlStyles['secondary']} small ${controlStyles['small']}`}
                disabled={disabled}
                key={targetKey(target)}
                onClick={() => narrow(target)}
              >
                <span>
                  <small>{targetKindLabel(target.kind, t)}</small> {target.name}
                </span>
                <ArrowRight size={13} aria-hidden="true" />
              </button>
            ))}
          </div>
        </div>
      )}
      <footer className={`${styles['host-overview-note']}`}>
        <span>{t('Automatic log reads are limited to four local containers.')}</span>
        {source && (
          <time dateTime={source.observed_at}>
            {t('Observed')} {utc(source.observed_at)}
          </time>
        )}
      </footer>
    </section>
  );
}
