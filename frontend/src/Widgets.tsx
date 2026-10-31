import { isMessageKey } from './messages';
import { useLocale } from './locale';
import { useId, useState } from 'react';
import { ArrowUpRight, ChevronDown, FileText, Layers, LockKeyhole, Terminal, Box } from 'lucide-react';
import type { Action, Evidence, Widget } from './contracts';
import { Status } from './ui';
import { bytes, utc } from './format';
import { EnvironmentContent, LogContent } from './RuntimeContent';
import { CardActions } from './CardActions';
import { widgetSource } from './evidence';

interface Props {
  widget: Widget;
  selected: string | null;
  evidence: Evidence[];
  inspect: (id: string) => void;
  review: (action: Action) => void;
  outcomes: Record<string, Action>;
  demo?: boolean;
  embedded?: boolean;
}

/** Label widgets with observed source data, keeping narrative out of fact cards. */
export function WidgetCard({
  widget,
  selected,
  evidence,
  inspect,
  review,
  outcomes,
  demo = false,
  embedded = false,
}: Props) {
  const { t, locale } = useLocale();
  const [expanded, setExpanded] = useState(true);
  const logsOpen = !embedded || expanded;
  const logId = useId();
  const primary = widgetSource(widget, evidence);
  const observed = evidence.find((row) => row.id === primary);
  const Heading = embedded ? 'h4' : 'h3';
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
    <section
      className={`widget widget-${widget.widget_type}${linked ? ' linked' : ''}${embedded ? ' embedded' : ''}`}
      role={embedded ? 'group' : undefined}
      aria-label={name}
      data-evidence-id={primary}
    >
      <header className="widget-head">
        <Heading>
          <Icon size={16} />
          {name}
          {embedded && widget.widget_type === 'container_status' && <Status state={widget.snapshot.state} />}
        </Heading>
        {embedded && widget.widget_type === 'log_anomalies' && (
          <button
            className="text-button log-toggle"
            type="button"
            data-log-toggle
            aria-label={t(expanded ? 'Collapse logs' : 'Expand logs')}
            aria-expanded={expanded}
            aria-controls={logId}
            onClick={() => setExpanded((value) => !value)}
          >
            <ChevronDown size={14} className={expanded ? '' : 'collapsed'} />
            {t(expanded ? 'Collapse logs' : 'Expand logs')}
          </button>
        )}
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
      {embedded && widget.widget_type === 'log_anomalies' && (
        <div className="log-disclosure" data-open={!logsOpen} aria-hidden={logsOpen}>
          <div>
            <div className="log-collapsed-note">
              <span>
                {t('{count} lines returned', { count: widget.logs.entries.length })} ·{' '}
                {t(widget.logs.truncated ? 'Truncated · partial evidence' : 'Within requested bounds')}
              </span>
              {observed && <time dateTime={observed.observed_at}>{utc(observed.observed_at)}</time>}
            </div>
          </div>
        </div>
      )}
      {widget.widget_type === 'container_status' && (
        <>
          {!embedded && (
            <div className="container-heading">
              <strong>{widget.snapshot.name}</strong>
              <Status state={widget.snapshot.state} />
            </div>
          )}
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
          {widget.recommendation && (
            <div className="action-suggestion" aria-label={t('Suggested by model')}>
              <span>{t('Suggested by model')}</span>
              {widget.recommendation.reason && (
                <p>
                  {demo && isMessageKey(widget.recommendation.reason)
                    ? t(widget.recommendation.reason)
                    : widget.recommendation.reason}
                </p>
              )}
              {primary && (
                <button className="text-button evidence-link" onClick={() => inspect(primary)}>
                  {t('Supporting evidence')}
                  <ArrowUpRight size={13} />
                </button>
              )}
            </div>
          )}
          <footer className="widget-foot">
            <time dateTime={widget.snapshot.observed_at}>{utc(widget.snapshot.observed_at)}</time>
            <CardActions
              actions={widget.actions}
              recommendedId={widget.recommendation?.action_id}
              outcomes={outcomes}
              review={review}
            />
          </footer>
        </>
      )}
      {widget.widget_type === 'log_anomalies' && (
        <div id={logId} className="log-disclosure" data-open={logsOpen} aria-hidden={!logsOpen} inert={!logsOpen}>
          <div>
            <LogContent logs={widget.logs} grouped={embedded} />
            <footer className="widget-foot">
              <span>{t('Docker logs · sanitized text')}</span>
              {observed && <time dateTime={observed.observed_at}>{utc(observed.observed_at)}</time>}
              {widget.logs.truncated && <span className="warning-text">{t('Earlier output was omitted')}</span>}
            </footer>
          </div>
        </div>
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
          <EnvironmentContent variables={widget.variables} />
          {observed && (
            <footer className="widget-foot">
              <time dateTime={observed.observed_at}>{utc(observed.observed_at)}</time>
            </footer>
          )}
        </>
      )}
    </section>
  );
}

/** Show a selected server observation as safe text with its exact provenance. */
export function EvidenceInspector({ evidence, resourceName }: { evidence?: Evidence; resourceName?: string }) {
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
              <dt>{t(evidence.container_id ? 'Container' : 'Scope')}</dt>
              <dd title={evidence.container_id ?? undefined}>
                {resourceName ?? (evidence.container_id ? `${evidence.container_id.slice(0, 12)}…` : t('Host scope'))}
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
              <span>{t('Observation ID')}</span>
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
