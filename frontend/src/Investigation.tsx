import { diagnosticErrors, diagnosticOperations, isMessageKey, stateLabel, targetKindLabel } from './messages';
import { useLocale } from './locale';
import { useState } from 'react';
import {
  ArrowDown,
  ArrowRight,
  ArrowUpRight,
  Check,
  LoaderCircle,
  Square,
  Terminal,
  MessageSquare,
  TriangleAlert,
} from 'lucide-react';
import { targetKey } from './contracts';
import type { Action, Answer, Container, DiagnosticTarget, GroupTarget, Transport } from './contracts';
import { ActionReview } from './ActionReview';
import { EvidenceInspector, WidgetCard } from './Widgets';
import type { useInvestigation } from './useInvestigation';
import { DiagnosticTrace } from './DiagnosticTrace';
import { GroupReport } from './GroupReport';
import { EvidenceTrail } from './EvidenceTrail';
import { containerWidgetGroups, evidenceResource, widgetSource } from './evidence';
import { ContainerEvidence } from './ContainerEvidence';
import { GroupClarification } from './GroupClarification';
import { HostOverview } from './HostOverview';
import { utc } from './format';

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
  const { t, locale } = useLocale();
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
        {turns.length > 1 && (
          <details className="session-turns">
            <summary>
              {t(client.history ? '{count} saved questions' : '{count} turns in this tab session', {
                count: turns.length,
              })}
            </summary>
            <div>
              {turns.map((row) => (
                <button
                  className="history-row"
                  key={row.id}
                  onClick={() => setView({ id: row.id, latest: latest!.id })}
                >
                  <span>
                    {row.exampleQuery && isMessageKey(row.query) ? t(row.query) : row.query}
                    {row.target && (
                      <span className="muted">
                        {' '}
                        · {targetKindLabel(row.target.kind, t)} / {row.target.name}
                      </span>
                    )}
                  </span>
                  <span className="muted">{stateLabel(row.state, t, true)}</span>
                </button>
              ))}
            </div>
          </details>
        )}
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
      <form
        className="composer"
        aria-labelledby="composer-title"
        onSubmit={(event) => {
          event.preventDefault();
          submit(draft, group ?? target);
        }}
      >
        <div className="composer-heading">
          <MessageSquare size={18} aria-hidden="true" />
          <h2 id="composer-title">{t('Ask DockSight')}</h2>
          <p>{t(running ? 'Following the evidence' : turn ? 'Continue the investigation' : 'Read-only diagnosis')}</p>
        </div>
        <div className="composer-entry">
          <label htmlFor="query" className="sr-only">
            {t(turn ? 'Continue the investigation' : 'Ask DockSight')}
          </label>
          <textarea
            id="query"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            maxLength={4000}
            rows={3}
            aria-describedby="composer-scope"
            placeholder={t(turn ? 'What else should we check?' : 'Why did this container exit?')}
            onKeyDown={(event) => {
              if (
                (event.metaKey || event.ctrlKey) &&
                event.key === 'Enter' &&
                !running &&
                !blocked &&
                draft.trim() &&
                host
              ) {
                event.preventDefault();
                submit(draft, group ?? target);
              }
            }}
          />
          <div className="composer-foot">
            <span id="composer-scope">
              <span className="scope-dot" />
              {host || t('Select a host')}
              {group && (
                <span className="composer-group">
                  {' '}
                  · {group.kind === 'compose' ? 'Compose' : 'Swarm'} / {group.name}
                </span>
              )}
              <span className="composer-hint">{t(' · Read-only diagnosis')}</span>
            </span>
            <div className="composer-actions">
              <span className="query-limit">
                {draft.length
                  ? `${draft.length.toLocaleString(locale)} / ${Number(4000).toLocaleString(locale)}`
                  : t('Ctrl / ⌘ + Enter to send')}
              </span>
              {running ? (
                <button type="button" className="primary" onClick={stop}>
                  <Square size={12} />
                  {t('Stop diagnosis')}
                </button>
              ) : (
                <button className="primary" type="submit" disabled={blocked || !draft.trim() || !host}>
                  {t('Investigate')}
                  <ArrowRight size={15} />
                </button>
              )}
            </div>
          </div>
        </div>
      </form>
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

/** Keep each container's retained observations together beside their sources and group context. */
function AnswerGrid({
  answer,
  selected,
  inspect,
  review,
  outcomes,
  demo,
}: {
  answer: Answer;
  selected: string | null;
  inspect: (id: string) => void;
  review: (action: Action) => void;
  outcomes: Record<string, Action>;
  demo: boolean;
}) {
  const { t } = useLocale();
  const evidence = answer.evidence.find((row) => row.id === selected);
  const card = (widget: Answer['widgets'][number], index: number, embedded = false) => (
    <WidgetCard
      key={`${widget.widget_type}-${index}`}
      widget={widget}
      selected={selected}
      evidence={answer.evidence}
      inspect={inspect}
      review={review}
      outcomes={outcomes}
      demo={demo}
      embedded={embedded}
    />
  );
  return (
    <div className="answer-grid">
      <div className="facts-column">
        <div className="column-label">
          <h2>{t('Runtime evidence')}</h2>
          <span>{t('Server observations')}</span>
        </div>
        {containerWidgetGroups(answer).map((group) => (
          <ContainerEvidence
            key={group.key}
            group={group}
            active={group.widgets.some((widget) => widgetSource(widget, answer.evidence) === selected)}
          >
            {group.widgets.map((widget, index) => card(widget, index, true))}
          </ContainerEvidence>
        ))}
        {!answer.widgets.length && <p className="empty-note">{t('No UI cards were returned for this answer.')}</p>}
      </div>
      <aside className="context-column" aria-label={t('Evidence and context')}>
        <div className="column-label">
          <h2>{t('Evidence trail')}</h2>
          <span>{t('{count} references', { count: answer.evidence.length })}</span>
        </div>
        <EvidenceTrail answer={answer} selected={selected} inspect={inspect} />
        <EvidenceInspector
          evidence={evidence}
          resourceName={evidence ? evidenceResource(evidence, answer).name : undefined}
        />
        {answer.widgets
          .filter((row) => row.widget_type === 'compose_stack')
          .map((widget, index) => card(widget, index))}
      </aside>
    </div>
  );
}
