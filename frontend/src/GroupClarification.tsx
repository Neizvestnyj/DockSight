import { ArrowRight, Layers } from 'lucide-react';
import type { GroupSelection, GroupTarget } from './contracts';
import { useLocale } from './locale';

/** Continue the original question only after the operator selects a server-observed group. */
export function GroupClarification({
  selection,
  host,
  disabled,
  choose,
}: {
  selection: GroupSelection;
  host: string;
  disabled: boolean;
  choose: (target: GroupTarget) => void;
}) {
  const { t } = useLocale();
  return (
    <section className="group-clarification" aria-label={t('Group clarification')}>
      <div className="clarification-heading">
        <Layers size={18} aria-hidden="true" />
        <h2>{t('Choose a group to continue')}</h2>
        <span>{host}</span>
      </div>
      <p>{t('Select the observed group you meant. The original question will continue with that exact scope.')}</p>
      <div className="group-choices">
        {selection.candidates.map((target) => {
          const kind = t(target.kind === 'compose' ? 'Docker Compose' : 'Docker Swarm');
          return (
            <button
              className="secondary"
              key={`${target.kind}:${target.name}`}
              type="button"
              disabled={disabled}
              onClick={() => choose(target)}
            >
              <span>
                <small>{kind}</small> <strong>{target.name}</strong>
              </span>
              <ArrowRight size={16} aria-hidden="true" />
            </button>
          );
        })}
      </div>
    </section>
  );
}
