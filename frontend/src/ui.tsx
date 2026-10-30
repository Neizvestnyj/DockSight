import { stateLabel } from './messages';
import { useLocale } from './locale';
import { useEffect, useId, useRef, type MouseEvent, type ReactNode } from 'react';
import { X } from 'lucide-react';

/** Pair a semantic status color with readable text rather than relying on color alone. */
export function Status({ state, action = false }: { state: string; action?: boolean }) {
  const { t } = useLocale();
  const tone = ['failed', 'dead', 'exited'].includes(state)
    ? 'negative'
    : ['restarting', 'expired', 'indeterminate'].includes(state)
      ? 'warning'
      : ['running', 'succeeded'].includes(state)
        ? 'positive'
        : 'neutral';
  return (
    <span className={`status ${tone}`}>
      <span aria-hidden="true" className="status-dot" />
      {stateLabel(state, t, action)}
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
  return (
    <dialog
      ref={dialog}
      className={`modal${className ? ` ${className}` : ''}`}
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
      <header className="modal-head">
        <h2 id={titleId}>{title}</h2>
        <button className="icon-button" aria-label={t('Close dialog')} onClick={close}>
          <X size={18} />
        </button>
      </header>
      {children}
    </dialog>
  );
}

/** Display the supplied vector wordmark with its original letterforms and colors. */
export function Logo() {
  return <img className="brand-logo" src="/brand/docksight.svg" alt="DockSight" width="968" height="238" />;
}
