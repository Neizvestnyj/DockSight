import { isMessageKey, stateLabel, targetKindLabel } from '../../../shared/i18n/messages';
import { useLocale } from '../../../shared/i18n/locale';
import type { Turn } from '../model/turns';

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
    <details className="session-turns">
      <summary>
        {t(saved ? '{count} saved questions' : '{count} turns in this tab session', { count: turns.length })}
      </summary>
      <div>
        {turns.map((row) => (
          <button className="history-row" key={row.id} onClick={() => choose(row.id)}>
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
  );
}
