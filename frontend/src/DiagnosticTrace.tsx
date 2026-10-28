import { useEffect, useId, useState } from 'react';
import { ArrowLeft, Braces, Check, ChevronDown, Copy, LoaderCircle, Square, TriangleAlert } from 'lucide-react';
import type { TraceStep } from './contracts';
import { utc } from './format';
import { useLocale } from './locale';
import { diagnosticOperations } from './messages';
import type { Turn } from './useInvestigation';

/** Keep debugging data inside its original turn, with no provider requests or browser persistence. */
export function DiagnosticTrace({ turn, host, demo }: { turn: Turn; host: string; demo: boolean }) {
  const { t, locale } = useLocale();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showDetail, setShowDetail] = useState(false);
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'failed'>('idle');
  const detailsId = useId();
  const trace = turn.trace;
  const selected = trace?.steps.find((step) => step.id === selectedId) ?? trace?.steps.at(-1);

  useEffect(() => {
    if (!selectedId || !window.matchMedia?.('(max-width: 1100px)').matches) return;
    const target = document.getElementById(showDetail ? detailsId : `${detailsId}-${selectedId}`);
    target?.focus({ preventScroll: true });
    target?.scrollIntoView({ block: 'nearest' });
  }, [detailsId, selectedId, showDetail]);

  /** Copy only the public trace, excluding the operator's query, credentials, and action execution keys. */
  async function copyTrace() {
    try {
      await navigator.clipboard.writeText(
        JSON.stringify(
          {
            schema_version: 1,
            simulated: demo,
            host,
            request_id: turn.requestId ?? null,
            turn_id: turn.serverTurnId ?? null,
            state: turn.state,
            ...trace,
          },
          null,
          2,
        ),
      );
      setCopyState('copied');
    } catch {
      setCopyState('failed');
    }
  }

  return (
    <details className="diagnostic-trace">
      <summary>
        <ChevronDown size={15} className="trace-chevron" aria-hidden="true" />
        <Braces size={15} aria-hidden="true" />
        <span>{t('Diagnostic trace')}</span>
        <span className="trace-count">
          {trace ? t('{count} recorded steps', { count: trace.steps.length }) : t('Not recorded')}
        </span>
      </summary>
      <div className="trace-content">
        {!trace ? (
          <p className="empty-note">
            {t('No trace was recorded for this turn. Run a new diagnosis to capture its steps.')}
          </p>
        ) : (
          <>
            <div className="trace-heading">
              <div>
                <strong>
                  {trace.provider ?? t('Unavailable')} · <code>{trace.model ?? t('Unavailable')}</code>
                </strong>
                <p>{demo ? t('Simulated trace · no model request') : t('Recorded by the diagnostic backend')}</p>
              </div>
              <div className="trace-copy">
                <span role="status">
                  {copyState === 'copied' ? t('Trace copied') : copyState === 'failed' ? t('Could not copy trace') : ''}
                </span>
                <button className="secondary" onClick={() => void copyTrace()}>
                  <Copy size={14} />
                  {t('Copy trace')}
                </button>
              </div>
            </div>
            <dl className="trace-identifiers">
              <div>
                <dt>{t('Request ID')}</dt>
                <dd>
                  <code>{turn.requestId ?? t('Unavailable')}</code>
                </dd>
              </div>
              <div>
                <dt>{t('Turn ID')}</dt>
                <dd>
                  <code>{turn.serverTurnId ?? t('Unavailable')}</code>
                </dd>
              </div>
              <div>
                <dt>{t('Started')}</dt>
                <dd>
                  {trace.started_at ? (
                    <time dateTime={trace.started_at}>
                      {trace.started_at.slice(0, 10)} · {utc(trace.started_at)}
                    </time>
                  ) : (
                    t('Unavailable')
                  )}
                </dd>
              </div>
            </dl>
            <div className={`trace-layout${showDetail ? ' show-detail' : ''}`}>
              <ol className="trace-steps" aria-label={t('Recorded diagnostic steps')}>
                {trace.steps.map((step) => {
                  const interrupted = step.state === 'running' && turn.state !== 'running';
                  const label = diagnosticOperations[step.operation];
                  return (
                    <li key={step.id}>
                      <button
                        id={`${detailsId}-${step.id}`}
                        className={`trace-step ${selected?.id === step.id ? 'selected' : ''}`}
                        aria-pressed={selected?.id === step.id}
                        aria-controls={detailsId}
                        onClick={() => {
                          setSelectedId(step.id);
                          setShowDetail(true);
                        }}
                      >
                        <span className={`trace-mark ${step.state}`} aria-hidden="true">
                          {interrupted ? (
                            <Square size={14} />
                          ) : step.state === 'running' ? (
                            <LoaderCircle size={14} className="spin" />
                          ) : step.state === 'failed' ? (
                            <TriangleAlert size={14} />
                          ) : (
                            <Check size={14} />
                          )}
                        </span>
                        <span className="trace-step-name">
                          {label ? t(label) : step.operation}
                          <small>
                            {t(
                              interrupted
                                ? 'Interrupted'
                                : step.state === 'running'
                                  ? 'Running'
                                  : step.state === 'failed'
                                    ? 'Failed'
                                    : 'Succeeded',
                            )}
                          </small>
                        </span>
                        <span className="trace-duration">
                          {step.duration_ms === null
                            ? '—'
                            : t('{duration} ms', { duration: step.duration_ms.toLocaleString(locale) })}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ol>
              <section id={detailsId} className="trace-detail" aria-label={t('Trace step details')} tabIndex={-1}>
                <button className="text-button trace-back" onClick={() => setShowDetail(false)}>
                  <ArrowLeft size={14} />
                  {t('Back to steps')}
                </button>
                {selected ? (
                  <StepDetails step={selected} interrupted={selected.state === 'running' && turn.state !== 'running'} />
                ) : (
                  <p className="empty-note">{t('Waiting for the first recorded step…')}</p>
                )}
              </section>
            </div>
            <p className="trace-note">
              {t('This trace stays in this tab. Prompts, hidden reasoning, and provider-native data are excluded.')}
            </p>
          </>
        )}
      </div>
    </details>
  );
}

/** Render measured values and sanitized proposal text without interpreting model content as markup. */
function StepDetails({ step, interrupted }: { step: TraceStep; interrupted: boolean }) {
  const { t, locale } = useLocale();
  const exploration = step.operation === 'collect_evidence';
  const label = diagnosticOperations[step.operation];
  const count = (value: number | null) => (value === null ? t('Unavailable') : value.toLocaleString(locale));
  return (
    <>
      <h3>{label ? t(label) : step.operation}</h3>
      <p className="section-note">
        <time dateTime={step.started_at}>{utc(step.started_at)}</time>
        {step.finished_at && (
          <>
            {' '}
            → <time dateTime={step.finished_at}>{utc(step.finished_at)}</time>
          </>
        )}
      </p>
      {interrupted && (
        <p className="trace-interrupted">
          {t('The stream ended before this step reported a result. Its completion is unknown.')}
        </p>
      )}
      <dl className="trace-measures">
        <div>
          <dt>{t('Duration')}</dt>
          <dd>
            {step.duration_ms === null
              ? t('Unavailable')
              : t('{duration} ms', { duration: step.duration_ms.toLocaleString(locale) })}
          </dd>
        </div>
        {step.kind === 'model' && (
          <>
            <div>
              <dt>{t('Input tokens')}</dt>
              <dd>{count(step.input_tokens)}</dd>
            </div>
            <div>
              <dt>{t('Output tokens')}</dt>
              <dd>{count(step.output_tokens)}</dd>
            </div>
          </>
        )}
      </dl>
      {step.code && (
        <p className="trace-error">
          <TriangleAlert size={14} />
          <code>{step.code}</code>
        </p>
      )}
      {step.issues.length > 0 && (
        <ul className="trace-issues">
          {step.issues.map((issue, index) => (
            <li key={index}>
              <code>{issue.loc.join('.') || '$'}</code>
              <span>{issue.type}</span>
            </li>
          ))}
        </ul>
      )}
      {step.kind === 'validation' && step.state === 'succeeded' && (
        <p>{t('The schema and evidence references passed validation. Cards were assembled by the backend.')}</p>
      )}
      {step.kind === 'model' && (
        <>
          <h4>{t(exploration ? 'Model response · sanitized' : 'Model proposal · sanitized')}</h4>
          <p className="section-note">
            {t(
              exploration
                ? 'Adapter output: assistant text and requested tools. Tool arguments are untrusted until validated.'
                : 'Recognized proposal fields before card assembly. Formatting and secrets may be changed.',
            )}
          </p>
          {step.response !== null ? (
            <pre
              className="trace-response"
              tabIndex={0}
              aria-label={t(exploration ? 'Sanitized model response' : 'Sanitized model proposal')}
            >
              {step.response}
            </pre>
          ) : (
            <p className="empty-note">
              {t(
                exploration
                  ? 'No displayable model response has been received.'
                  : 'Proposal unavailable. Invalid or oversized response bodies are withheld.',
              )}
            </p>
          )}
          {step.response_truncated && (
            <p className="warning-text">{t('Preview limited to 16 KiB. The displayed response is incomplete.')}</p>
          )}
        </>
      )}
    </>
  );
}
