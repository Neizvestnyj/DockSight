import {
  diagnosticErrors,
  diagnosticOperations,
  isMessageKey,
  stateLabel,
  targetKindLabel,
} from '../../../shared/i18n/messages';
import { useLocale } from '../../../shared/i18n/locale';
import { useState } from 'react';
import { ArrowDown, ArrowRight, ArrowUpRight, Check, LoaderCircle, Terminal, TriangleAlert } from 'lucide-react';
import { targetKey } from '../../../shared/contracts/contracts';
import type { Action, Container, DiagnosticTarget, GroupTarget, Transport } from '../../../shared/contracts/contracts';
import { ActionReview } from '../../actions';
import type { useInvestigation } from '../model/useInvestigation';
import { DiagnosticTrace } from './DiagnosticTrace';
import { GroupReport } from './GroupReport';
import { AnswerGrid } from './AnswerGrid';
import { QuestionComposer } from './QuestionComposer';
import { TurnNavigation } from './TurnNavigation';
import { GroupClarification } from './GroupClarification';
import { HostOverview } from './HostOverview';
import { utc } from '../../../shared/lib/format';

interface Props {
  investigation: ReturnType<typeof useInvestigation>;
  client: Transport;
  demo: boolean;
  containers: Container[];
  draft: string;
  setDraft: (value: string) => void;
  host: string;
  blocked?: boolean;
  group?: GroupTarget;
  target?: DiagnosticTarget;
}

/** Compose conclusions, typed observations, and an always-available follow-up query. */
export function Investigation({
  investigation,
  client,
  demo,
  containers,
  draft,
  setDraft,
  host,
  blocked = false,
  group,
  target,
}: Props) {
  const { t } = useLocale();
  const { turns, running, run, chooseTarget, stop } = investigation;
  const [view, setView] = useState<{ id: string; latest: string } | null>(null);
  const latest = turns.at(-1);
  const turn = (view?.latest === latest?.id && turns.find((row) => row.id === view?.id)) || latest;
  const [reference, setReference] = useState<string | null>(null);
  const [review, setReview] = useState<Action | null>(null);
  const [outcomes, setOutcomes] = useState<Record<string, Action>>({});
  const [keys] = useState(() => new Map<string, string>());
  const answer = turn?.answer;
  const displayedQuery = turn?.exampleQuery && isMessageKey(turn.query) ? t(turn.query) : turn?.query;
  const localError = turn?.errorSource === 'client' && turn.error;
  const diagnosticError =
    turn?.code && Object.hasOwn(diagnosticErrors, turn.code) ? diagnosticErrors[turn.code] : undefined;
  const errorMessage = localError
    ? t(isMessageKey(localError) ? localError : 'Connection failed. Retry manually.')
    : diagnosticError
      ? t(diagnosticError)
      : demo && turn?.error && isMessageKey(turn.error)
        ? t(turn.error)
        : turn?.error;
  const selected = answer?.evidence.find((row) => row.id === reference) ?? answer?.evidence[0];
  const narrative = (text: string) => (demo && isMessageKey(text) ? t(text) : text);

  /** Move keyboard focus with the selected source so the evidence chain works without a pointer. */
  function inspect(id: string) {
    setReference(id);
    for (const card of document.querySelectorAll<HTMLElement>('[data-evidence-id]')) {
      if (card.dataset.evidenceId === id)
        card.querySelector<HTMLButtonElement>('[data-log-toggle][aria-expanded="false"]')?.click();
    }
    const panel = document.getElementById('evidence-observation');
    panel?.focus({ preventScroll: true });
    panel?.scrollIntoView?.({ behavior: 'smooth', block: 'nearest' });
  }

  /** Submit one host-bound query and keep its text available for a manual retry. */
  function submit(query: string, target?: DiagnosticTarget) {
    if (blocked) return;
    setView(null);
    void run(query, false, target);
    if (demo) setDraft('');
  }

  /** Start an explicit scope-specific turn while retaining the operator's unrelated draft and history. */
  function narrow(target: DiagnosticTarget) {
    if (blocked || running) return;
    const query =
      target.kind === 'container'
        ? t('Investigate this container ({id}). What happened, and what evidence supports it?', { id: target.id })
        : t('Investigate the {kind} group {name}. Check every member and explain the failures.', {
            kind: target.kind === 'compose' ? 'Compose' : 'Swarm',
            name: target.name,
          });
    setView(null);
    const boundedTarget =
      client.history && target.kind === 'container' ? { ...target, name: target.name.slice(0, 256) } : target;
    void run(query, true, boundedTarget);
  }

  return (
    <>
      <div className="investigation-content">
        {investigation.error && (
          <p className="inline-warning" role="status">
            {investigation.errorSource !== 'server' && isMessageKey(investigation.error)
              ? t(investigation.error)
              : investigation.error}
          </p>
        )}
        {investigation.nextCursor && (
          <button
            className="secondary"
            disabled={investigation.olderLoading}
            onClick={() => void investigation.older()}
          >
            {t('Older answers')}
          </button>
        )}
        <TurnNavigation
          turns={turns}
          saved={Boolean(client.history)}
          choose={(id) => setView({ id, latest: latest!.id })}
        />
        {turn ? (
          <>
            <div className="query-line">
              <span className="query-glyph" aria-hidden="true">
                ↳
              </span>
              <h2>{displayedQuery}</h2>
              <span className="muted query-author">{t('Operator')}</span>
            </div>
            {turn.createdAt && (
              <p className="section-note">
                {t('Saved {time} · historical evidence', { time: utc(turn.createdAt, true) })}
              </p>
            )}
            {turn.attempts && turn.attempts.length > 1 && (
              <details className="saved-attempts">
                <summary>{t('{count} diagnostic attempts', { count: turn.attempts.length })}</summary>
                {turn.attempts.map((attempt) => (
                  <p key={attempt.id}>
                    <time dateTime={attempt.updated_at}>{utc(attempt.updated_at, true)}</time> ·{' '}
                    {stateLabel(attempt.state, t, true)} · <code>{attempt.request_id}</code>
                  </p>
                ))}
              </details>
            )}
            {turn.target && (
              <p className="section-note query-scope">
                {t('Scope')}: {targetKindLabel(turn.target.kind, t)} / {turn.target.name}
              </p>
            )}
            {turn.progress.length > 0 && (
              <div className="progress" role="status" aria-label={t('Diagnostic progress')}>
                {turn.progress.map((row, index) => (
                  <span key={index} className={row.state === 'failed' ? 'warning-text' : ''}>
                    {row.state === 'running' ? (
                      <LoaderCircle size={13} className="spin" />
                    ) : row.state === 'failed' ? (
                      <TriangleAlert size={13} />
                    ) : (
                      <Check size={13} />
                    )}
                    {diagnosticOperations[row.tool]
                      ? t(diagnosticOperations[row.tool]!)
                      : t('Read tool: {tool}', { tool: row.tool })}
                    {demo && row.state === 'running' ? t(' · simulated') : ''}
                  </span>
                ))}
              </div>
            )}
            {turn.state === 'running' && !answer && (
              <div className="collecting">
                <LoaderCircle className="spin" size={19} />
                <div>
                  <strong>{t('Following the evidence')}</strong>
                  <p>{t('Collecting read-only Docker observations. Cards arrive with the validated answer.')}</p>
                </div>
              </div>
            )}
            {answer && (
              <>
                <section className="conclusion" aria-label={t('Model explanation')}>
                  <div className="conclusion-label">
                    <span className="sight-line" aria-hidden="true" />
                    <h2>{t('Diagnostic conclusion')}</h2>
                    <span className={answer.uncertain ? 'uncertainty' : 'model-label'}>
                      {t(
                        answer.cause
                          ? answer.uncertain || answer.cause.unknowns.length
                            ? 'Partially explained'
                            : 'Model explanation'
                          : answer.uncertain
                            ? 'Cause uncertain'
                            : 'Model explanation',
                      )}
                    </span>
                  </div>
                  <p>{demo && isMessageKey(answer.summary) ? t(answer.summary) : answer.summary}</p>
                  {answer.cause && (
                    <dl className="cause-details">
                      <div>
                        <dt>{t('Immediate failure')}</dt>
                        <dd>{narrative(answer.cause.immediate)}</dd>
                      </div>
                      {answer.cause.underlying && (
                        <div>
                          <dt>{t('Underlying cause')}</dt>
                          <dd>{narrative(answer.cause.underlying)}</dd>
                        </div>
                      )}
                      {answer.cause.unknowns.length > 0 && (
                        <div>
                          <dt>{t('Still unknown')}</dt>
                          <dd>
                            {answer.cause.unknowns.map((text, index) => (
                              <p key={index}>{narrative(text)}</p>
                            ))}
                          </dd>
                        </div>
                      )}
                      <div>
                        <dt className="sr-only">{t('Source')}</dt>
                        <dd>
                          <button
                            type="button"
                            className="evidence-link"
                            onClick={() => inspect(answer.cause!.evidence_ids[0]!)}
                          >
                            {t('Supporting observations')}
                            <ArrowUpRight size={13} />
                          </button>
                        </dd>
                      </div>
                    </dl>
                  )}
                  {answer.uncertain && !answer.cause && (
                    <p className="uncertain-note">
                      {t('The collected observations do not establish a definitive cause.')}
                    </p>
                  )}
                  <div className="evidence-chain">
                    <span>{t('Trace the evidence')}</span>
                    <ArrowRight size={13} />
                    {answer.evidence
                      .filter((row) => row.kind === 'container' || row.kind === 'logs')
                      .slice(0, 3)
                      .map((row) => (
                        <button
                          className="evidence-link"
                          key={row.id}
                          aria-label={t(row.kind === 'logs' ? 'View log evidence' : 'View container evidence')}
                          onClick={() => inspect(row.id)}
                        >
                          {t(row.kind === 'logs' ? 'Log evidence' : 'Container evidence')}
                          <ArrowUpRight size={13} />
                        </button>
                      ))}
                    {!answer.evidence.length && <span>{t('No supporting evidence returned')}</span>}
                  </div>
                </section>
              </>
            )}
            {(turn.state === 'failed' || turn.state === 'stopped' || turn.state === 'interrupted') && (
              <section className="turn-error" aria-label={t('Diagnostic interruption')}>
                <TriangleAlert size={18} />
                <div>
                  <h3>{t(turn.state === 'stopped' ? 'Diagnosis stopped' : 'Diagnosis could not finish')}</h3>
                  <p role={turn.state === 'failed' ? 'alert' : undefined}>
                    {errorMessage ?? t('Collection was cancelled. Submit again when you are ready.')}
                  </p>
                  {turn.code && (
                    <p className="section-note">
                      {turn.code}
                      {turn.requestId ? t(' · Request {id}', { id: turn.requestId }) : ''}
                    </p>
                  )}
                  {localError && !isMessageKey(localError) && (
                    <details>
                      <summary>{t('Technical details')}</summary>
                      <p>{localError}</p>
                    </details>
                  )}
                  <button
                    className="secondary"
                    disabled={running || blocked || turn.code === 'history_unsupported'}
                    onClick={() => submit(turn.query, turn.target)}
                  >
                    {t('Retry diagnosis')}
                    <ArrowRight size={14} />
                  </button>
                </div>
              </section>
            )}
            {turn.state === 'awaiting_selection' && turn.selection && (
              <GroupClarification
                selection={turn.selection}
                host={host}
                disabled={running || blocked}
                choose={(target) => {
                  setView({ id: turn.id, latest: latest!.id });
                  void chooseTarget(turn.id, target);
                }}
              />
            )}
            <DiagnosticTrace
              key={`${turn.id}:${turn.target ? targetKey(turn.target) : ''}`}
              turn={turn}
              host={host}
              demo={demo}
            />
            {answer?.group && <GroupReport report={answer.group} evidence={answer.evidence} inspect={inspect} />}
            {answer?.host_overview && (
              <HostOverview
                report={answer.host_overview}
                evidence={answer.evidence}
                inspect={inspect}
                narrow={narrow}
                disabled={running || blocked}
              />
            )}
            {answer && (
              <AnswerGrid
                key={`answer-${turn.id}`}
                answer={answer}
                selected={selected?.id ?? null}
                inspect={inspect}
                review={setReview}
                outcomes={outcomes}
                demo={demo}
              />
            )}
          </>
        ) : (
          <section className="first-run">
            <div className="first-run-mark">
              <Terminal size={26} />
            </div>
            <h2>{t('Start an investigation')}</h2>
            <p>
              {t('Ask what happened on {host}. DockSight will gather observations before explaining them.', {
                host: host || t('a configured host'),
              })}
            </p>
            <button className="secondary" onClick={() => setDraft(t('Which containers need attention, and why?'))}>
              {t('Check this host')}
              <ArrowDown size={14} />
            </button>
          </section>
        )}
      </div>
      <QuestionComposer
        draft={draft}
        setDraft={setDraft}
        host={host}
        blocked={blocked}
        running={running}
        hasTurn={Boolean(turn)}
        group={group}
        target={target}
        submit={submit}
        stop={stop}
      />
      {review && (
        <ActionReview
          key={review.id}
          action={outcomes[review.id] ?? review}
          client={client}
          demo={demo}
          name={containers.find((row) => row.id === review.container_id)?.name}
          close={() => setReview(null)}
          keys={keys}
          update={(action) => setOutcomes((previous) => ({ ...previous, [action.id]: action }))}
        />
      )}
    </>
  );
}
