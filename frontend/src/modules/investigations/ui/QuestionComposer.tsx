import sharedStyles from '../../../shared/ui/Shared.module.css';
import controlStyles from '../../../shared/ui/Controls.module.css';
import { ArrowRight, MessageSquare, Square } from 'lucide-react';
import type { DiagnosticTarget, GroupTarget } from '../../../shared/contracts/contracts';
import { useLocale } from '../../../shared/i18n/locale';
import styles from './QuestionComposer.module.css';

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
      className={styles['composer']}
      aria-labelledby="composer-title"
      onSubmit={(event) => {
        event.preventDefault();
        submit(draft, group ?? target);
      }}
    >
      <div className={styles['composer-heading']}>
        <MessageSquare size={18} aria-hidden="true" />
        <h2 id="composer-title">{t('Ask DockSight')}</h2>
        <p>{t(running ? 'Following the evidence' : hasTurn ? 'Continue the investigation' : 'Read-only diagnosis')}</p>
      </div>
      <div className={styles['composer-entry']}>
        <label htmlFor="query" className={`sr-only ${sharedStyles['sr-only']}`}>
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
        <div className={`${styles['composer-foot']} composer-foot`}>
          <span id="composer-scope">
            <span className={`scope-dot ${sharedStyles['scope-dot']}`} />
            {host || t('Select a host')}
            {group && (
              <span className={styles['composer-group']}>
                {' '}
                · {group.kind === 'compose' ? 'Compose' : 'Swarm'} / {group.name}
              </span>
            )}
            <span className={styles['composer-hint']}>{t(' · Read-only diagnosis')}</span>
          </span>
          <div className={styles['composer-actions']}>
            <span className={`${styles['query-limit']} query-limit`}>
              {draft.length
                ? `${draft.length.toLocaleString(locale)} / ${Number(4000).toLocaleString(locale)}`
                : t('Ctrl / ⌘ + Enter to send')}
            </span>
            {running ? (
              <button type="button" className={`primary ${controlStyles['primary']}`} onClick={stop}>
                <Square size={12} />
                {t('Stop diagnosis')}
              </button>
            ) : (
              <button
                className={`primary ${controlStyles['primary']}`}
                type="submit"
                disabled={blocked || !draft.trim() || !host}
              >
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
