import controlStyles from '../../../shared/ui/Controls.module.css';
import { useEffect, useRef, useState } from 'react';
import { ArrowUpRight, ChevronDown, SlidersHorizontal } from 'lucide-react';
import type { Action } from '../../../shared/contracts/contracts';
import { useLocale } from '../../../shared/i18n/locale';
import { stateLabel } from '../../../shared/i18n/messages';
import styles from './CardActions.module.css';

/** Keep ordinary operations in a disclosure and expose only an explicit server-linked model suggestion. */
export function CardActions({
  actions,
  recommendedId,
  outcomes,
  review,
}: {
  actions: Action[];
  recommendedId?: string | null;
  outcomes: Record<string, Action>;
  review: (action: Action) => void;
}) {
  const { t } = useLocale();
  const disclosure = useRef<HTMLDetailsElement>(null);
  const trigger = useRef<HTMLElement>(null);
  const [open, setOpen] = useState(false);
  const suggested = actions.find((action) => action.id === recommendedId);
  const ordinary = actions.filter((action) => action.id !== suggested?.id);

  useEffect(() => {
    /** Close an open disclosure when the operator moves to another control. */
    function outside(event: PointerEvent) {
      if (disclosure.current?.open && event.target instanceof Node && !disclosure.current.contains(event.target))
        setOpen(false);
    }
    document.addEventListener('pointerdown', outside);
    return () => document.removeEventListener('pointerdown', outside);
  }, []);

  /** Close the list and focus its persistent trigger before opening the confirmation dialog. */
  function choose(action: Action) {
    setOpen(false);
    trigger.current?.focus();
    review(outcomes[action.id] ?? action);
  }

  /** Describe the current lifecycle state without manufacturing another action ID. */
  function label(action: Action) {
    const current = outcomes[action.id] ?? action;
    return current.state === 'prepared'
      ? t(`Review ${current.operation}`)
      : `${t(current.operation)}: ${stateLabel(current.state, t)}`;
  }

  return (
    <div className={`${styles['actions']} actions`}>
      {suggested && (
        <button
          className={`secondary ${controlStyles['secondary']} small ${controlStyles['small']} ${styles['action-trigger']}`}
          onClick={() => review(outcomes[suggested.id] ?? suggested)}
        >
          {label(suggested)}
          <ArrowUpRight size={13} />
        </button>
      )}
      {ordinary.length > 0 && (
        /* eslint-disable jsx-a11y-x/no-noninteractive-element-interactions -- Native details handles disclosure; Escape restores focus. */
        <details
          className={`${styles['card-actions-menu']} card-actions-menu`}
          name="container-operations"
          ref={disclosure}
          open={open}
          onToggle={(event) => setOpen(event.currentTarget.open)}
          onKeyDown={(event) => {
            if (event.key !== 'Escape' || !disclosure.current?.open) return;
            event.preventDefault();
            setOpen(false);
            trigger.current?.focus();
          }}
        >
          <summary
            className={`secondary ${controlStyles['secondary']} small ${controlStyles['small']} ${styles['action-trigger']}`}
            ref={trigger}
            onClick={(event) => {
              event.preventDefault();
              setOpen(!open);
            }}
          >
            <SlidersHorizontal size={14} aria-hidden="true" />
            {t('Actions')}
            <ChevronDown size={13} />
          </summary>
          {open && (
            <div className={`${styles['available-operations']}`} role="group" aria-label={t('Available operations')}>
              {ordinary.map((action) => (
                <button key={action.id} onClick={() => choose(action)}>
                  {label(action)}
                  <ArrowUpRight size={13} />
                </button>
              ))}
            </div>
          )}
        </details>
        /* eslint-enable jsx-a11y-x/no-noninteractive-element-interactions */
      )}
      {!actions.length && <span>{t('No permitted actions')}</span>}
    </div>
  );
}
