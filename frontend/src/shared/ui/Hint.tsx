import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { CircleHelp } from 'lucide-react';
import { useFloatingPanel } from './useFloatingPanel';
import styles from './Hint.module.css';

type Props = { children?: string; control?: ReactNode } & (
  | { label: string; button?: never }
  | { label?: never; button: { className: string; content: ReactNode; onClick: () => void } }
);

/** Make optional guidance available to pointer, keyboard, and touch users without permanent page copy. */
export function Hint({ label, children, control, button }: Props) {
  const id = useId();
  const root = useRef<HTMLSpanElement>(null);
  const hideTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const [open, setOpen] = useState(false);
  const visible = open && Boolean(children);
  const { anchor: trigger, panel } = useFloatingPanel<HTMLButtonElement, HTMLSpanElement>(
    visible,
    false,
    button ? 'above' : 'below',
  );
  useEffect(() => {
    if (!visible) return;
    /** Close touch-opened help when the operator continues elsewhere. */
    function dismiss(event: PointerEvent) {
      if (event.target instanceof Node && !root.current?.contains(event.target)) setOpen(false);
    }
    /** Dismiss hover-opened help without requiring keyboard focus on the trigger. */
    function dismissKey(event: KeyboardEvent) {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      event.stopPropagation();
      setOpen(false);
    }
    document.addEventListener('pointerdown', dismiss);
    document.addEventListener('keydown', dismissKey, true);
    return () => {
      document.removeEventListener('pointerdown', dismiss);
      document.removeEventListener('keydown', dismissKey, true);
      clearTimeout(hideTimer.current);
    };
  }, [visible]);

  /** Cancel delayed dismissal when a pointer crosses the small gap into the floating help. */
  function show() {
    clearTimeout(hideTimer.current);
    setOpen(true);
  }

  /** Allow pointer travel without hiding help that still belongs to the focused trigger. */
  function hideSoon() {
    hideTimer.current = setTimeout(() => {
      if (!root.current?.contains(document.activeElement)) setOpen(false);
    }, 160);
  }

  /** Keep a blocked action focusable while limiting its activation to showing the reason. */
  function renderTrigger() {
    if (!button && !children) return null;
    return (
      <button
        ref={trigger}
        type="button"
        className={button?.className ?? styles['hint-trigger']}
        aria-label={label}
        aria-disabled={button && Boolean(children)}
        aria-describedby={visible || (button && children) ? id : undefined}
        onFocus={children ? show : undefined}
        onBlur={children ? () => setOpen(false) : undefined}
        onClick={children ? show : button?.onClick}
      >
        {button ? button.content : <CircleHelp size={14} aria-hidden="true" />}
      </button>
    );
  }

  return (
    <span
      ref={root}
      className={control ? `${styles.hint} ${styles['hint-with-control']}` : styles.hint}
      onMouseEnter={children ? show : undefined}
      onMouseLeave={visible ? hideSoon : undefined}
    >
      {control}
      {renderTrigger()}
      {visible ? (
        <span
          key="popup"
          ref={panel}
          id={id}
          role="tooltip"
          className={styles['hint-popup']}
          data-action={button ? '' : undefined}
          popover="manual"
        >
          {children}
        </span>
      ) : (
        button &&
        children && (
          <span key="description" id={id} hidden>
            {children}
          </span>
        )
      )}
    </span>
  );
}
