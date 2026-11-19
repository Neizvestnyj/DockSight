import controlStyles from '../../../shared/ui/Controls.module.css';
import type { Action, Answer } from '../../../shared/contracts/contracts';
import { useLocale } from '../../../shared/i18n/locale';
import { containerWidgetGroups, evidenceResource, widgetSource } from '../model/evidence';
import { ContainerEvidence } from './ContainerEvidence';
import { EvidenceTrail } from './EvidenceTrail';
import { EvidenceInspector, WidgetCard } from './Widgets';
import styles from './AnswerGrid.module.css';

/** Keep each container's retained observations together beside their sources and group context. */
export function AnswerGrid({
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
    <div className={`${styles['answer-grid']}`}>
      <div className={`${styles['facts-column']}`}>
        <div className={`${styles['column-label']}`}>
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
        {!answer.widgets.length && (
          <p className={`empty-note ${controlStyles['empty-note']}`}>
            {t('No UI cards were returned for this answer.')}
          </p>
        )}
      </div>
      <aside className={`${styles['context-column']}`} aria-label={t('Evidence and context')}>
        <div className={`${styles['column-label']}`}>
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
