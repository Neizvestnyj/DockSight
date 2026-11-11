import { ArrowRight, MessageSquare, Square } from 'lucide-react';
import type { DiagnosticTarget, GroupTarget } from '../../../shared/contracts/contracts';
import { useLocale } from '../../../shared/i18n/locale';

/** Render the existing question controls while the investigation owns its draft and lifecycle. */
export function QuestionComposer({
  draft,
  setDraft,
  host,
  blocked,
  running,
  hasTurn,
  group,
  target,
  submit,
  stop,
}: {
  draft: string;
  setDraft: (value: string) => void;
  host: string;
  blocked: boolean;
  running: boolean;
  hasTurn: boolean;
  group?: GroupTarget;
  target?: DiagnosticTarget;
  submit: (query: string, target?: DiagnosticTarget) => void;
  stop: () => void;
}) {
  const { t, locale } = useLocale();
  return (
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
        <p>{t(running ? 'Following the evidence' : hasTurn ? 'Continue the investigation' : 'Read-only diagnosis')}</p>
      </div>
      <div className="composer-entry">
        <label htmlFor="query" className="sr-only">
          {t(hasTurn ? 'Continue the investigation' : 'Ask DockSight')}
        </label>
        <textarea
          id="query"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          maxLength={4000}
          rows={3}
          aria-describedby="composer-scope"
          placeholder={t(hasTurn ? 'What else should we check?' : 'Why did this container exit?')}
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
  );
}
