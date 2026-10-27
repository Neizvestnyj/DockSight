import { useState } from 'react';
import {
  ArrowDown,
  ArrowRight,
  ArrowUpRight,
  Check,
  LoaderCircle,
  Square,
  Terminal,
  TriangleAlert,
} from 'lucide-react';
import type { Action, Answer, Container, Transport } from './contracts';
import { ActionReview } from './ActionReview';
import { EvidenceInspector, WidgetCard } from './Widgets';
import type { useInvestigation } from './useInvestigation';

const toolNames: Record<string, string> = {
  list_containers: 'Reading container inventory',
  inspect_container: 'Inspecting container state',
  get_container_logs: 'Reading container logs',
  get_container_stats: 'Measuring CPU and memory',
  get_container_env: 'Reading allowlisted environment',
  list_stacks: 'Reading stack context',
};
interface Props {
  investigation: ReturnType<typeof useInvestigation>;
  client: Transport;
  demo: boolean;
  containers: Container[];
  draft: string;
  setDraft: (value: string) => void;
  host: string;
}

/** Compose conclusions, typed observations, and an always-available follow-up query. */
export function Investigation({ investigation, client, demo, containers, draft, setDraft, host }: Props) {
  const { turns, running, run, stop } = investigation;
  const [viewId, setViewId] = useState<string | null>(null);
  const turn = turns.find((row) => row.id === viewId) ?? turns.at(-1);
  const [reference, setReference] = useState<string | null>(null);
  const [review, setReview] = useState<Action | null>(null);
  const [outcomes, setOutcomes] = useState<Record<string, Action>>({});
  const [keys] = useState(() => new Map<string, string>());
  const answer = turn?.answer;
  const selected = answer?.evidence.find((row) => row.id === reference) ?? answer?.evidence[0];

  /** Move keyboard focus with the selected source so the evidence chain works without a pointer. */
  function inspect(id: string) {
    setReference(id);
    const panel = document.getElementById('evidence-observation');
    panel?.focus({ preventScroll: true });
    panel?.scrollIntoView?.({ behavior: 'smooth', block: 'nearest' });
  }

  /** Submit one host-bound query and keep its text available for a manual retry. */
  function submit(query: string) {
    setViewId(null);
    void run(query);
    setDraft('');
  }

  return (
    <>
      <div className="investigation-content">
        {turns.length > 1 && (
          <details className="session-turns">
            <summary>{turns.length} turns in this tab session</summary>
            <div>
              {turns.map((row) => (
                <button className="history-row" key={row.id} onClick={() => setViewId(row.id)}>
                  <span>{row.query}</span>
                  <span className="muted">{row.state}</span>
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
              <h2>{turn.query}</h2>
              <span className="muted query-author">Operator</span>
            </div>
            {turn.progress.length > 0 && (
              <div className="progress" role="status" aria-label="Diagnostic progress">
                {turn.progress.map((row, index) => (
                  <span key={index} className={row.state === 'failed' ? 'warning-text' : ''}>
                    {row.state === 'running' ? (
                      <LoaderCircle size={13} className="spin" />
                    ) : row.state === 'failed' ? (
                      <TriangleAlert size={13} />
                    ) : (
                      <Check size={13} />
                    )}
                    {toolNames[row.tool] ?? `Read tool: ${row.tool}`}
                    {demo && row.state === 'running' ? ' · simulated' : ''}
                  </span>
                ))}
              </div>
            )}
            {turn.state === 'running' && !answer && (
              <div className="collecting">
                <LoaderCircle className="spin" size={19} />
                <div>
                  <strong>Following the evidence</strong>
                  <p>Collecting read-only Docker observations. Cards arrive with the validated answer.</p>
                </div>
              </div>
            )}
            {answer && (
              <>
                <section className="conclusion" aria-label="Model explanation">
                  <div className="conclusion-label">
                    <span className="sight-line" aria-hidden="true" />
                    <h2>Diagnostic conclusion</h2>
                    <span className={answer.uncertain ? 'uncertainty' : 'model-label'}>
                      {answer.uncertain ? 'Cause uncertain' : 'Model explanation'}
                    </span>
                  </div>
                  <p>{answer.summary}</p>
                  {answer.uncertain && (
                    <p className="uncertain-note">The collected observations do not establish a definitive cause.</p>
                  )}
                  <div className="evidence-chain">
                    <span>Trace the evidence</span>
                    <ArrowRight size={13} />
                    {answer.evidence
                      .filter((row) => row.kind === 'container' || row.kind === 'logs')
                      .slice(0, 3)
                      .map((row) => (
                        <button
                          className="evidence-link"
                          key={row.id}
                          aria-label={`View ${row.kind === 'logs' ? 'log' : 'container'} evidence`}
                          onClick={() => inspect(row.id)}
                        >
                          {row.kind === 'logs' ? 'Log evidence' : 'Container evidence'}
                          <ArrowUpRight size={13} />
                        </button>
                      ))}
                    {!answer.evidence.length && <span>No supporting evidence returned</span>}
                  </div>
                </section>
                <AnswerGrid
                  answer={answer}
                  selected={selected?.id ?? null}
                  inspect={inspect}
                  review={setReview}
                  outcomes={outcomes}
                  containers={containers}
                />
              </>
            )}
            {(turn.state === 'failed' || turn.state === 'stopped') && (
              <section className="turn-error" aria-label="Diagnostic interruption">
                <TriangleAlert size={18} />
                <div>
                  <h3>{turn.state === 'stopped' ? 'Diagnosis stopped' : 'Diagnosis could not finish'}</h3>
                  <p role={turn.state === 'failed' ? 'alert' : undefined}>
                    {turn.error ?? 'Collection was cancelled. Submit again when you are ready.'}
                  </p>
                  {turn.code && (
                    <p className="section-note">
                      {turn.code}
                      {turn.requestId ? ` · Request ${turn.requestId}` : ''}
                    </p>
                  )}
                  <button className="secondary" disabled={running} onClick={() => submit(turn.query)}>
                    Retry diagnosis
                    <ArrowRight size={14} />
                  </button>
                </div>
              </section>
            )}
          </>
        ) : (
          <section className="first-run">
            <div className="first-run-mark">
              <Terminal size={26} />
            </div>
            <h2>Start an investigation</h2>
            <p>
              Ask what happened on {host || 'a configured host'}. DockSight will gather observations before explaining
              them.
            </p>
            <button className="secondary" onClick={() => setDraft('Which containers need attention, and why?')}>
              Check this host
              <ArrowDown size={14} />
            </button>
          </section>
        )}
      </div>
      <form
        className="composer"
        onSubmit={(event) => {
          event.preventDefault();
          submit(draft);
        }}
      >
        <label htmlFor="query">{turn ? 'Continue the investigation' : 'Ask DockSight'}</label>
        <textarea
          id="query"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          maxLength={4000}
          rows={2}
          placeholder={turn ? 'What else should we check?' : 'Why did this container exit?'}
          onKeyDown={(event) => {
            if ((event.metaKey || event.ctrlKey) && event.key === 'Enter' && !running && draft.trim() && host) {
              event.preventDefault();
              submit(draft);
            }
          }}
        />
        <div className="composer-foot">
          <span>
            <span className="scope-dot" />
            {host || 'Select a host'}
            <span className="composer-hint"> · Read-only diagnosis</span>
          </span>
          {running ? (
            <button type="button" className="primary" onClick={stop}>
              <Square size={12} />
              Stop diagnosis
            </button>
          ) : (
            <button className="primary" type="submit" disabled={!draft.trim() || !host}>
              Investigate
              <ArrowRight size={15} />
            </button>
          )}
        </div>
        <span className="query-limit">
          {draft.length ? `${draft.length.toLocaleString()} / 4,000` : 'Ctrl / ⌘ + Enter to send'}
        </span>
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

/** Balance the two diagnostic fact widgets against provenance and contextual observations. */
function AnswerGrid({
  answer,
  selected,
  inspect,
  review,
  outcomes,
  containers,
}: {
  answer: Answer;
  selected: string | null;
  inspect: (id: string) => void;
  review: (action: Action) => void;
  outcomes: Record<string, Action>;
  containers: Container[];
}) {
  const evidence = answer.evidence.find((row) => row.id === selected);
  const card = (widget: Answer['widgets'][number], index: number) => (
    <WidgetCard
      key={`${widget.widget_type}-${index}`}
      widget={widget}
      selected={selected}
      evidence={answer.evidence}
      inspect={inspect}
      review={review}
      outcomes={outcomes}
    />
  );
  return (
    <div className="answer-grid">
      <div className="facts-column">
        <div className="column-label">
          <h2>Runtime evidence</h2>
          <span>Server observations</span>
        </div>
        {answer.widgets
          .filter((row) => row.widget_type === 'container_status' || row.widget_type === 'log_anomalies')
          .map(card)}
        {!answer.widgets.length && <p className="empty-note">No UI cards were returned for this answer.</p>}
      </div>
      <aside className="context-column" aria-label="Evidence and context">
        <div className="column-label">
          <h2>Evidence trail</h2>
          <span>{answer.evidence.length} references</span>
        </div>
        <div className="evidence-picker">
          {answer.evidence.map((row, index) => (
            <button
              key={row.id}
              onClick={() => inspect(row.id)}
              className={selected === row.id ? 'selected' : ''}
              aria-pressed={selected === row.id}
              aria-label={`Inspect ${row.kind === 'container' ? 'State' : row.kind === 'stats' ? 'Metrics' : row.kind} observation ${index + 1}`}
            >
              {row.kind === 'container'
                ? 'State'
                : row.kind === 'logs'
                  ? 'Logs'
                  : row.kind === 'env'
                    ? 'Env'
                    : row.kind === 'stats'
                      ? 'Metrics'
                      : 'Stack'}
            </button>
          ))}
        </div>
        <EvidenceInspector
          evidence={evidence}
          containerName={containers.find((row) => row.id === evidence?.container_id)?.name}
        />
        {answer.widgets
          .filter((row) => row.widget_type === 'compose_stack' || row.widget_type === 'env_inspector')
          .map(card)}
      </aside>
    </div>
  );
}
