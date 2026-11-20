import sharedStyles from './Shared.module.css';
import controlStyles from './Controls.module.css';
import feedbackStyles from './Feedback.module.css';
import { stateLabel } from '../i18n/messages';
import { useLocale } from '../i18n/locale';
import { useEffect, useId, useRef, type MouseEvent, type ReactNode } from 'react';
import { X } from 'lucide-react';
import type { Container } from '../contracts/contracts';
import styles from './Status.module.css';
import localStyles from './Modal.module.css';

/** Pair a semantic status color with readable text rather than relying on color alone. */
export function Status({ state, action = false }: { state: string; action?: boolean }) {
  const { t } = useLocale();
  const tone = ['failed', 'dead'].includes(state)
    ? 'negative'
    : ['restarting', 'expired', 'indeterminate'].includes(state)
      ? 'warning'
      : ['running', 'succeeded'].includes(state)
        ? 'positive'
        : 'neutral';
  return (
    <span className={`${styles.status} status ${tone} ${feedbackStyles[tone]}`}>
      <span aria-hidden="true" className={`${styles['status-dot']}`} />
      {stateLabel(state, t, action)}
    </span>
  );
}

type HealthObservation = { state: string } & Pick<Container, 'health' | 'last_healthcheck'>;

/** Label process state and healthcheck separately in compact inventory and member lists. */
export function ContainerStatus(observation: HealthObservation) {
  const { t } = useLocale();
  const { state } = observation;
  return (
    <span className={`${styles['container-status']} container-status`}>
      <Status state={state} />
      <span className={`${styles['health-summary']}`}>
        <span className={`${styles['health-caption']} health-caption`}>
          {t(state === 'running' ? 'Healthcheck' : 'Last healthcheck')}
        </span>
        <HealthStatus {...observation} />
      </span>
    </span>
  );
}

/** Keep the reported healthcheck in its own fact row, identifying retained results for stopped processes. */
export function HealthFact(observation: HealthObservation) {
  const { t } = useLocale();
  return (
    <dl className={`${styles['health-fact']} health-fact`}>
      <dt>{t(observation.state === 'running' ? 'Healthcheck' : 'Last healthcheck')}</dt>
      <dd>
        <HealthStatus {...observation} />
      </dd>
    </dl>
  );
}

const healthPresentation = {
  healthy: { label: 'Health: healthy', tone: 'positive' },
  unhealthy: { label: 'Health: unhealthy', tone: 'negative' },
  starting: { label: 'Health: starting', tone: 'warning' },
  passed: { label: 'Healthcheck passed', tone: 'positive' },
  failed: { label: 'Healthcheck failed', tone: 'negative' },
  unknown: { label: 'Health: not reported', tone: 'neutral' },
} as const;

/** Use live monitor health for running processes and recorded probe results elsewhere. */
function HealthStatus({ state, health, last_healthcheck }: HealthObservation) {
  const { t } = useLocale();
  const { label, tone } = healthPresentation[(state === 'running' ? health : last_healthcheck) ?? 'unknown'];
  return (
    <span
      className={`${styles.status} ${styles['health-status']} status health-status ${tone} ${feedbackStyles[tone]}`}
      title={t('Docker healthcheck')}
    >
      <span aria-hidden="true" className={`${styles['status-dot']}`} />
      {t(label)}
    </span>
  );
}

/** Recognize native backdrop clicks while treating dialog padding and descendants as inside. */
function isBackdrop(event: MouseEvent<HTMLDialogElement>): boolean {
  if (event.target !== event.currentTarget) return false;
  const { left, right, top, bottom } = event.currentTarget.getBoundingClientRect();
  return event.clientX < left || event.clientX > right || event.clientY < top || event.clientY > bottom;
}

/** Contain focus, dismiss backdrop clicks and restore the invoking control without treating text drags as clicks. */
export function Modal({
  title,
  close,
  children,
  returnFocusId,
  className,
}: {
  title: string;
  close: () => void;
  children: ReactNode;
  returnFocusId?: string;
  className?: string;
}) {
  const { t } = useLocale();
  const titleId = useId();
  const dialog = useRef<HTMLDialogElement>(null);
  const backdropPress = useRef(false);
  useEffect(() => {
    const element = dialog.current;
    const previous = document.activeElement;
    element?.showModal?.();
    // jsdom has no modal implementation; the open attribute preserves accessible tests.
    if (element && !element.open) element.setAttribute('open', '');
    return () => {
      element?.close?.();
      const target = (returnFocusId && document.getElementById(returnFocusId)) || previous;
      if (target instanceof HTMLElement && target.isConnected) target.focus();
    };
  }, [returnFocusId]);
  /* eslint-disable jsx-a11y-x/no-noninteractive-element-interactions -- Native dialog handles cancel and backdrop dismissal. */
  return (
    <dialog
      ref={dialog}
      className={`${localStyles.modal} modal${className ? ` ${className}` : ''}`}
      aria-labelledby={titleId}
      onPointerDown={(event) => {
        backdropPress.current = event.isPrimary && event.button === 0 && isBackdrop(event);
      }}
      onPointerCancel={() => {
        backdropPress.current = false;
      }}
      onClick={(event) => {
        const dismiss = backdropPress.current && isBackdrop(event);
        backdropPress.current = false;
        if (dismiss) close();
      }}
      onCancel={(event) => {
        event.preventDefault();
        close();
      }}
      onKeyDown={(event) => {
        if (event.key !== 'Tab') return;
        const controls = Array.from(
          event.currentTarget.querySelectorAll<HTMLElement>(
            'button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]',
          ),
        ).filter((element) => element.getClientRects().length > 0);
        const first = controls[0];
        const last = controls.at(-1);
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        }
        if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }}
    >
      <header className={`${localStyles['modal-head']} modal-head`}>
        <h2 id={titleId}>{title}</h2>
        <button
          className={`icon-button ${controlStyles['icon-button']}`}
          aria-label={t('Close dialog')}
          onClick={close}
        >
          <X size={18} />
        </button>
      </header>
      {children}
    </dialog>
  );
  /* eslint-enable jsx-a11y-x/no-noninteractive-element-interactions */
}

/** Display the supplied vector wordmark with its original letterforms and colors. */
export function Logo() {
  return (
    <img
      className={`brand-logo ${sharedStyles['brand-logo']}`}
      src="/brand/docksight.svg"
      alt="DockSight"
      width="968"
      height="238"
    />
  );
}
