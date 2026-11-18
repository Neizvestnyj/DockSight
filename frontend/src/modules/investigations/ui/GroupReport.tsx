import controlStyles from '../../../shared/ui/Controls.module.css';
import { ArrowUpRight, Layers } from 'lucide-react';
import type { Evidence, GroupInspection } from '../../../shared/contracts/contracts';
import { useLocale } from '../../../shared/i18n/locale';
import { utc } from '../../../shared/lib/format';
import { ContainerStatus } from '../../../shared/ui/ui';
import styles from './GroupReport.module.css';

/** Present server-owned group coverage independently of which detail cards the model selected. */
export function GroupReport({
  report,
  evidence,
  inspect,
}: {
  report: GroupInspection;
  evidence: Evidence[];
  inspect: (id: string) => void;
}) {
  const { t } = useLocale();
  const { summary, logs } = report;
  const members = summary.members ?? [];
  const observed = evidence.find((row) => row.id === report.evidence_id);
  const collected = logs.filter((row) => row.state === 'collected').length;
  return (
    <section className={`${styles['group-report']}`} aria-label={t('Group observations')}>
      <header>
        <Layers size={18} />
        <div>
          <span className={`section-note ${controlStyles['section-note']}`}>
            {summary.kind === 'compose' ? t('Compose project') : t('Swarm stack')}
          </span>
          <h2>{summary.name}</h2>
        </div>
        <strong>
          {summary.running} / {summary.total}
          <span>{t(summary.kind === 'compose' ? 'containers running' : 'task replicas running')}</span>
        </strong>
        <button
          className={`evidence-link ${controlStyles['evidence-link']}`}
          onClick={() => inspect(report.evidence_id)}
        >
          {t('Source')}
          <ArrowUpRight size={13} />
        </button>
      </header>
      {summary.truncated && <p className={`${styles['group-warning']}`}>{t('Group inventory may be incomplete.')}</p>}
      {report.inventory_code && (
        <p className={`${styles['group-warning']}`}>
          {t('Local container discovery failed. Group observations are retained.')}
          <span className="mono"> {report.inventory_code}</span>
        </p>
      )}
      {summary.kind === 'swarm' && (
        <p className={`section-note ${controlStyles['section-note']} ${styles['group-note']}`}>
          {t('Service counts include remote nodes. Container logs are limited to this engine.')}
        </p>
      )}
      {/* eslint-disable-next-line jsx-a11y-x/no-noninteractive-tabindex -- The scrollable region needs keyboard focus. */}
      <div className={`${styles['group-members']}`} tabIndex={0} role="region" aria-label={t('Group members')}>
        {members.map((row) => {
          const log = logs.find((item) => item.container_id === row.id);
          return (
            <div className={`${styles['group-member']} group-member`} key={row.id}>
              <div>
                <strong title={row.name}>{row.name}</strong>
                <span className={`mono section-note ${controlStyles['section-note']}`}>
                  {row.kind === 'container' ? row.id.slice(0, 12) : t('Service')}
                </span>
              </div>
              <span className={`${styles['group-member-state']}`}>
                {row.kind === 'service' ? (
                  <span
                    className={
                      row.state === 'running' ? styles['healthy-text'] : `warning-text ${controlStyles['warning-text']}`
                    }
                  >{`${row.running} / ${row.total} ${t('task replicas')}`}</span>
                ) : (
                  <ContainerStatus state={row.state} health={row.health} />
                )}
                {row.exit_code !== null && row.state === 'exited' && (
                  <small>
                    {t('Exit code')} {row.exit_code}
                  </small>
                )}
              </span>
              {log &&
                (log.evidence_id ? (
                  <button
                    className={`evidence-link ${controlStyles['evidence-link']}`}
                    onClick={() => inspect(log.evidence_id!)}
                  >
                    {t('Logs')}
                    <ArrowUpRight size={13} />
                  </button>
                ) : (
                  <span
                    className={`section-note ${controlStyles['section-note']} warning-text ${controlStyles['warning-text']}`}
                  >
                    {t(log.state === 'failed' ? 'Log read failed' : 'Logs not collected')}
                    {log.code && (
                      <small>
                        {t(log.code === 'group_log_limit' ? 'Collection limit reached' : 'Read unavailable')}
                      </small>
                    )}
                  </span>
                ))}
            </div>
          );
        })}
      </div>
      {summary.kind === 'swarm' && logs.length > 0 && (
        <div className={`${styles['group-local-logs']}`}>
          <h3>{t('Local container log coverage')}</h3>
          {logs.map((log) => (
            <div className={`${styles['group-member']} group-member`} key={log.container_id}>
              <div>
                <strong>{log.name}</strong>
                <span className={`mono section-note ${controlStyles['section-note']}`}>
                  {log.container_id.slice(0, 12)}
                </span>
              </div>
              {log.evidence_id ? (
                <button
                  className={`evidence-link ${controlStyles['evidence-link']}`}
                  onClick={() => inspect(log.evidence_id!)}
                >
                  {t('Logs')}
                  <ArrowUpRight size={13} />
                </button>
              ) : (
                <span
                  className={`section-note ${controlStyles['section-note']} warning-text ${controlStyles['warning-text']}`}
                >
                  {t(log.state === 'failed' ? 'Log read failed' : 'Logs not collected')}
                </span>
              )}
            </div>
          ))}
        </div>
      )}
      <footer>
        <span>{t('Problem containers with logs: {collected} / {total}', { collected, total: logs.length })}</span>
        {observed && (
          <span>
            {t('Observed')} {utc(observed.observed_at)}
          </span>
        )}
      </footer>
    </section>
  );
}
