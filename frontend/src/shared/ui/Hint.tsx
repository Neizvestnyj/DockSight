import { useEffect, useId, useRef, useState } from 'react';
import { CircleHelp } from 'lucide-react';
import { useFloatingPanel } from './useFloatingPanel';

/** Make optional guidance available to pointer, keyboard, and touch users without permanent page copy. */
export function Hint({ label, children }: { label: string; children: string }) {
  const id = useId();
  const root = useRef<HTMLSpanElement>(null);
  const hideTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const [open, setOpen] = useState(false);
  const { anchor: trigger, panel } = useFloatingPanel<HTMLButtonElement, HTMLSpanElement>(open);
  useEffect(() => {
    if (!open) return;
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
  }, [open]);

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

  return (
    <span ref={root} className="hint" onMouseEnter={show} onMouseLeave={hideSoon}>
      <button
        ref={trigger}
        type="button"
        className="hint-trigger"
        aria-label={label}
        aria-describedby={open ? id : undefined}
        onFocus={show}
        onBlur={() => setOpen(false)}
        onClick={show}
      >
        <CircleHelp size={14} aria-hidden="true" />
      </button>
      {open && (
        <span ref={panel} id={id} role="tooltip" className="hint-popup" popover="manual">
          {children}
        </span>
      )}
    </span>
  );
}
