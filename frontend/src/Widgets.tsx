import { stateLabel } from './messages';
import { useLocale } from './locale';
import { ArrowUpRight, FileText, Layers, LockKeyhole, Terminal, Box } from 'lucide-react';
import type { Action, Evidence, Widget } from './contracts';
import { Status } from './ui';
import { bytes, utc } from './format';

interface Props {
  widget: Widget;
  selected: string | null;
  evidence: Evidence[];
  inspect: (id: string) => void;
  review: (action: Action) => void;
  outcomes: Record<string, Action>;
}

/** Label widgets with observed source data, keeping narrative out of fact cards. */
export function WidgetCard({ widget, selected, evidence, inspect, review, outcomes }: Props) {
  const { t, locale } = useLocale();
  const primary =
    widget.widget_type === 'log_anomalies'
      ? evidence.find((row) => row.kind === 'logs' && widget.evidence_ids.includes(row.id))?.id
      : widget.evidence_ids[0];
  const linked = selected === primary;
  const name = t(
    widget.widget_type === 'container_status'
      ? 'Container status'
      : widget.widget_type === 'log_anomalies'
        ? 'Container logs'
        : widget.widget_type === 'compose_stack'
          ? 'Stack context'
          : 'Environment',
  );
  const Icon =
    widget.widget_type === 'container_status'
      ? Box
      : widget.widget_type === 'log_anomalies'
        ? Terminal
        : widget.widget_type === 'compose_stack'
          ? Layers
          : LockKeyhole;
  return (
    <section className={`widget widget-${widget.widget_type}${linked ? ' linked' : ''}`} aria-label={name}>
      <header className="widget-head">
        <h3>
          <Icon size={16} />
          {name}
        </h3>
        {primary && (
          <button
            className="text-button source-link"
            onClick={() => inspect(primary)}
            aria-label={t('View {name} source', { name: name.toLowerCase() })}
          >
            <FileText size={13} />
            {t('Source')}
            <ArrowUpRight size={13} />
          </button>
        )}
      </header>
      {widget.widget_type === 'container_status' && (
        <>
          <div className="container-heading">
            <strong>{widget.snapshot.name}</strong>
            <Status state={widget.snapshot.state} />
          </div>
          <p className="image-name">
            <code>{widget.snapshot.image}</code>
          </p>
          <dl className="fact-strip">
            <div>
              <dt>{t('Exit code')}</dt>
              <dd>{widget.snapshot.exit_code}</dd>
            </div>
            <div>
              <dt>{t('OOM killed')}</dt>
              <dd>{t(widget.snapshot.oom_killed ? 'Yes' : 'No')}</dd>
            </div>
            <div>
              <dt>{t('Restarts')}</dt>
              <dd>{widget.snapshot.restart_count}</dd>
            </div>
            <div>
              <dt>{t('CPU')}</dt>
              <dd className={widget.snapshot.metrics.cpu_percent === null ? 'unavailable' : ''}>
                {widget.snapshot.metrics.cpu_percent === null
                  ? t('Unavailable')
                  : `${widget.snapshot.metrics.cpu_percent.toLocaleString(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`}
              </dd>
            </div>
          </dl>
          <div className="memory-row">
            <span>{t('Memory')}</span>
            <span>
              {bytes(widget.snapshot.metrics.memory_usage_bytes, locale, t('Unavailable'))}{' '}
              <span className="muted">
                / {bytes(widget.snapshot.metrics.memory_limit_bytes, locale, t('Unavailable'))}
              </span>
            </span>
          </div>
          <footer className="widget-foot">
            <time dateTime={widget.snapshot.observed_at}>{utc(widget.snapshot.observed_at)}</time>
            <div className="actions">
              {widget.actions.length ? (
                widget.actions.map((action) => {
                  const current = outcomes[action.id] ?? action;
                  return (
                    <button key={action.id} className="secondary small" onClick={() => review(current)}>
                      {current.state === 'prepared'
                        ? t(`Review ${current.operation}`)
                        : `${t(current.operation)}: ${stateLabel(current.state, t)}`}
                      <ArrowUpRight size={13} />
                    </button>
                  );
                })
              ) : (
                <span>{t('No permitted actions')}</span>
              )}
            </div>
          </footer>
        </>
      )}
      {widget.widget_type === 'log_anomalies' && (
        <>
          <div className="log-toolbar">
            <span>{t('{count} lines returned', { count: widget.logs.entries.length })}</span>
            <span>{t(widget.logs.truncated ? 'Truncated · partial evidence' : 'Within requested bounds')}</span>
          </div>
          <div className="logs" tabIndex={0} role="region" aria-label={t('Timestamped container logs')}>
            {widget.logs.entries.length ? (
              widget.logs.entries.map((entry, index) => (
                <div className="log-line" key={index}>
                  <time dateTime={entry.timestamp ?? undefined}>
                    {entry.timestamp ? utc(entry.timestamp).replace(' UTC', '') : t('No time')}
                  </time>
                  <code>{entry.message}</code>
                </div>
              ))
            ) : (
              <p>{t('No log entries returned. An empty log does not establish the cause.')}</p>
            )}
          </div>
          <footer className="widget-foot">
            <span>{t('Docker logs · sanitized text')}</span>
            {widget.logs.truncated && (
              <span className="warning-text">{t('Earlier or later output may be missing')}</span>
            )}
          </footer>
        </>
      )}
      {widget.widget_type === 'compose_stack' && (
        <div className="stack-list">
          {widget.stacks.length ? (
            widget.stacks.map((stack) => (
              <div className="stack-row" key={`${stack.kind}-${stack.name}`}>
                <div>
                  <strong>{stack.name}</strong>
                  <span className="muted">{t(stack.kind === 'compose' ? 'Docker Compose' : 'Docker Swarm')}</span>
                </div>
                <div className="stack-total">
                  <strong>
                    {stack.running}
                    <span className="muted"> / {stack.total}</span>
                  </strong>
                  <span className="muted">{t('running')}</span>
                </div>
                <div
                  className="stack-segments"
                  role="img"
                  aria-label={t('{running} of {total} running', { running: stack.running, total: stack.total })}
                >
                  {Array.from({ length: Math.min(stack.total, 32) }, (_, i) => (
                    <span className={i < stack.running ? 'is-running' : ''} key={i} />
                  ))}
                </div>
              </div>
            ))
          ) : (
            <p className="empty-note">{t('No stacks in this observation.')}</p>
          )}
        </div>
      )}
      {widget.widget_type === 'env_inspector' && (
        <>
          <p className="section-note">{t('Allowlisted variables · read only')}</p>
          <dl className="env-list">
            {Object.keys(widget.variables).length ? (
              Object.entries(widget.variables).map(([key, value]) => (
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
      )}
    </section>
  );
}

/** Show a selected server observation as safe text with its exact provenance. */
export function EvidenceInspector({ evidence, containerName }: { evidence?: Evidence; containerName?: string }) {
  const { t } = useLocale();
  const sources = {
    container: 'Docker inspect',
    logs: 'Docker logs',
    stats: 'Docker stats',
    stack: 'Docker stack inventory',
    env: 'Allowlisted environment',
  } as const;
  return (
    <section className="observation" tabIndex={-1} aria-label={t('Evidence observation')} id="evidence-observation">
      <header className="widget-head">
        <h3>{t('Observation')}</h3>
        <span className="observed-label">{t('Observed fact')}</span>
      </header>
      {evidence ? (
        <>
          <dl className="provenance">
            <div>
              <dt>{t('Source')}</dt>
              <dd>{t(sources[evidence.kind])}</dd>
            </div>
            <div>
              <dt>{t('Host')}</dt>
              <dd>{evidence.host}</dd>
            </div>
            <div>
              <dt>{t('Container')}</dt>
              <dd title={evidence.container_id ?? undefined}>
                {containerName ?? (evidence.container_id ? `${evidence.container_id.slice(0, 12)}…` : t('Host scope'))}
              </dd>
            </div>
            <div>
              <dt>{t('Observed')}</dt>
              <dd>
                <time dateTime={evidence.observed_at}>
                  {new Date(evidence.observed_at).toISOString().slice(0, 10)} · {utc(evidence.observed_at)}
                </time>
              </dd>
            </div>
          </dl>
          <details className="raw-evidence">
            <summary>{t('Inspect observation data')}</summary>
            <pre tabIndex={0}>{JSON.stringify(evidence.data, null, 2)}</pre>
            <p className="evidence-id">
              <code>{evidence.id}</code>
            </p>
          </details>
        </>
      ) : (
        <p className="empty-note">{t('Select an evidence reference to inspect its source and observation.')}</p>
      )}
    </section>
  );
}
