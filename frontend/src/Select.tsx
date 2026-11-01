import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react';
import { Check, ChevronDown } from 'lucide-react';
import { useFloatingPanel } from './useFloatingPanel';

export interface SelectOption<T extends string> {
  value: T;
  label: string;
  disabled?: boolean;
}

/** Offer a controlled single choice with reversible keyboard navigation and a custom floating listbox. */
export function Select<T extends string>({
  value,
  options,
  onChange,
  onReselect,
  label,
  id,
  disabled = false,
  describedBy,
  className = '',
}: {
  value: T;
  options: readonly SelectOption<T>[];
  onChange: (value: T) => void;
  onReselect?: (value: T) => void;
  label: string;
  id?: string;
  disabled?: boolean;
  describedBy?: string;
  className?: string;
}) {
  const generatedId = useId();
  const triggerId = id ?? generatedId;
  const listId = `${triggerId}-options`;
  const root = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  if (disabled && open) setOpen(false);
  const [active, setActive] = useState(value);
  const search = useRef({ text: '', time: 0 });
  const enabled = options.filter((row) => !row.disabled);
  const selected = options.find((row) => row.value === value);
  const initial = enabled.find((row) => row.value === value)?.value ?? enabled[0]?.value ?? value;
  const expanded = open && !disabled;
  const { anchor: trigger, panel } = useFloatingPanel<HTMLButtonElement, HTMLDivElement>(expanded, true);

  useEffect(() => {
    if (!expanded) return;
    /** Dismiss an outside pointer without selecting the tentative keyboard option. */
    function dismiss(event: PointerEvent) {
      if (event.target instanceof Node && !root.current?.contains(event.target)) setOpen(false);
    }
    document.addEventListener('pointerdown', dismiss);
    return () => document.removeEventListener('pointerdown', dismiss);
  }, [expanded]);

  useEffect(() => {
    if (expanded) panel.current?.querySelector('[data-active="true"]')?.scrollIntoView?.({ block: 'nearest' });
  }, [active, expanded, panel]);

  /** Start browsing from the current enabled value without changing the controlled selection. */
  function show() {
    setActive(initial);
    search.current = { text: '', time: 0 };
    setOpen(true);
  }

  /** Commit only an enabled, observed option; preserve the trigger as the keyboard focus owner. */
  function choose(next: T, reselect = true) {
    if (!enabled.some((row) => row.value === next)) return;
    if (next !== value) onChange(next);
    else if (reselect) onReselect?.(next);
    setOpen(false);
  }

  /** Move visual focus through enabled choices while keeping runtime or locale state unchanged. */
  function navigate(key: string) {
    if (!expanded) search.current = { text: '', time: 0 };
    const current = Math.max(
      0,
      enabled.findIndex((row) => row.value === (expanded ? active : initial)),
    );
    const destinations: Record<string, number> = {
      Home: 0,
      End: enabled.length - 1,
      ArrowDown: Math.min(current + 1, enabled.length - 1),
      ArrowUp: Math.max(current - 1, 0),
    };
    const openingArrow = !expanded && (key === 'ArrowDown' || key === 'ArrowUp');
    const index = openingArrow ? current : destinations[key];
    setActive(enabled[Math.max(0, index ?? 0)]?.value ?? value);
    setOpen(true);
  }

  /** Match labels incrementally, cycling repeated letters and skipping disabled choices. */
  function typeAhead(character: string) {
    const now = Date.now();
    const text = !expanded || now - search.current.time > 700 ? character : search.current.text + character;
    search.current = { text, time: now };
    const repeated = [...text].every((letter) => letter === character);
    const query = repeated ? character : text;
    const start = expanded ? enabled.findIndex((row) => row.value === active) : -1;
    const rows = [...enabled.slice(start + (repeated ? 1 : 0)), ...enabled.slice(0, start + 1)];
    const match = rows.find((row) => row.label.toLocaleLowerCase().startsWith(query.toLocaleLowerCase()));
    if (match) setActive(match.value);
    else if (!expanded) setActive(initial);
    setOpen(true);
  }

  /** Keep dismissal inside the menu so Escape does not also close its containing dialog. */
  function keyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key === 'Tab') {
      if (expanded) choose(active, false);
      return;
    }
    if (event.key === 'Escape' && expanded) {
      event.preventDefault();
      event.stopPropagation();
      setOpen(false);
      return;
    }
    if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
      event.preventDefault();
      navigate(event.key);
    } else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      if (expanded) choose(active);
      else show();
    } else if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
      event.preventDefault();
      typeAhead(event.key);
    }
  }

  return (
    <div ref={root} className={`select-control ${className}`}>
      <button
        ref={trigger}
        id={triggerId}
        type="button"
        role="combobox"
        className="select-trigger"
        aria-label={label}
        aria-describedby={describedBy}
        aria-expanded={expanded}
        aria-haspopup="listbox"
        aria-controls={expanded ? listId : undefined}
        aria-activedescendant={expanded ? `${listId}-${options.findIndex((row) => row.value === active)}` : undefined}
        disabled={disabled}
        onKeyDown={keyDown}
        onBlur={() => setOpen(false)}
        onClick={() => (expanded ? setOpen(false) : show())}
      >
        <span>{selected?.label ?? options[0]?.label ?? ''}</span>
        <ChevronDown size={15} aria-hidden="true" />
      </button>
      {expanded && (
        <div ref={panel} id={listId} role="listbox" aria-label={label} className="select-popup" popover="manual">
          {options.map((row, index) => (
            <div
              id={`${listId}-${index}`}
              key={row.value}
              role="option"
              aria-selected={row.value === value}
              aria-disabled={row.disabled || undefined}
              data-value={row.value}
              data-active={row.value === active}
              className="select-option"
              onPointerDown={(event) => event.preventDefault()}
              onPointerMove={() => !row.disabled && setActive(row.value)}
              onClick={(event) => {
                event.preventDefault();
                choose(row.value);
              }}
            >
              <span>{row.label}</span>
              {row.value === value && <Check size={15} aria-hidden="true" />}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
