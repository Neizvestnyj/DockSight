import { ArrowRight, Layers } from 'lucide-react';
import { targetKey } from './contracts';
import type { DiagnosticTarget, TargetSelection } from './contracts';
import { useLocale } from './locale';
import { targetKindLabel } from './messages';

/** Distinguish resource namespaces before continuing the original question with an exact observed target. */
export function GroupClarification({
  selection,
  host,
  disabled,
  choose,
}: {
  selection: TargetSelection;
  host: string;
  disabled: boolean;
  choose: (target: DiagnosticTarget) => void;
}) {
  const { t } = useLocale();
  const mixed = selection.candidates.some((target) => target.kind === 'container');
  return (
    <section className="group-clarification" aria-label={t(mixed ? 'Resource clarification' : 'Group clarification')}>
      <div className="clarification-heading">
        <Layers size={18} aria-hidden="true" />
        <h2>{t(mixed ? 'Which resource do you mean?' : 'Choose a group to continue')}</h2>
        <span>{host}</span>
      </div>
      <p>
        {t(
          mixed
            ? 'This name matches different resources. Choose one to continue the same question.'
            : 'Select the observed group you meant. The original question will continue with that exact scope.',
        )}
      </p>
      <div className="group-choices">
        {selection.candidates.map((target) => {
          const kind = targetKindLabel(target.kind, t);
          return (
            <button
              className="secondary"
              key={targetKey(target)}
              type="button"
              disabled={disabled}
              onClick={() => choose(target)}
            >
              <span>
                <small>{kind}</small> <strong>{target.name}</strong>
                {target.kind === 'container' && <small className="mono">{target.id.slice(0, 12)}</small>}
              </span>
              <ArrowRight size={16} aria-hidden="true" />
            </button>
          );
        })}
      </div>
    </section>
  );
}
