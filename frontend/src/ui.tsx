import { stateLabel } from './messages';
import { useLocale } from './locale';
import { useEffect, useId, useRef, type ReactNode } from 'react';
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

/** Use the native modal's focus containment and restore the invoking control on close. */
export function Modal({ title, close, children }: { title: string; close: () => void; children: ReactNode }) {
  const { t } = useLocale();
  const titleId = useId();
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = dialog.current;
    const previous = document.activeElement;
    element?.showModal?.();
    // jsdom has no modal implementation; the open attribute preserves accessible tests.
    if (element && !element.open) element.setAttribute('open', '');
    return () => {
      element?.close?.();
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus();
    };
  }, []);
  return (
    <dialog
      ref={dialog}
      className="modal"
      aria-labelledby={titleId}
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

/** Draw DockSight's container and observation crosshair as one product mark. */
export function Mark() {
  return (
    <svg className="brand-mark" viewBox="0 0 32 32" fill="none" aria-hidden="true">
      <path
        d="m16 3 12 7v12l-12 7L4 22V10Zm0 0v13m12-6-12 6L4 10m12 6v13M10 16h12M16 10v12"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinejoin="round"
      />
    </svg>
  );
}
