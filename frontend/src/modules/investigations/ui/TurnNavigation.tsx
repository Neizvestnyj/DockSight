import controlStyles from '../../../shared/ui/Controls.module.css';
import { isMessageKey, stateLabel, targetKindLabel } from '../../../shared/i18n/messages';
import { useLocale } from '../../../shared/i18n/locale';
import type { Turn } from '../model/turns';
import styles from './TurnNavigation.module.css';

/** Select a historical question without changing the active investigation. */
export function TurnNavigation({
  turns,
  saved,
  choose,
}: {
  turns: Turn[];
  saved: boolean;
  choose: (id: string) => void;
}) {
  const { t } = useLocale();
  if (turns.length <= 1) return null;
  return (
    <details className={`${styles['session-turns']} session-turns`}>
      <summary>
        {t(saved ? '{count} saved questions' : '{count} turns in this tab session', { count: turns.length })}
      </summary>
      <div>
        {turns.map((row) => (
          <button className={`${styles['history-row']} history-row`} key={row.id} onClick={() => choose(row.id)}>
            <span>
              {row.exampleQuery && isMessageKey(row.query) ? t(row.query) : row.query}
              {row.target && (
                <span className={`muted ${controlStyles['muted']}`}>
                  {' '}
                  · {targetKindLabel(row.target.kind, t)} / {row.target.name}
                </span>
              )}
            </span>
            <span className={`muted ${controlStyles['muted']}`}>{stateLabel(row.state, t, true)}</span>
          </button>
        ))}
      </div>
    </details>
  );
}
