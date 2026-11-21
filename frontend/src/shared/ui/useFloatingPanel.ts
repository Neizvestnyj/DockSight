import { useLayoutEffect, useRef } from 'react';

/** Keep a floating menu inside the viewport and above scrolling panels or modal content. */
export function useFloatingPanel<A extends HTMLElement, P extends HTMLElement>(
  open: boolean,
  matchWidth = false,
  placement: 'above' | 'below' = 'below',
) {
  const anchor = useRef<A>(null);
  const panel = useRef<P>(null);
  useLayoutEffect(() => {
    const target = anchor.current;
    const element = panel.current;
    if (!open || !target || !element) return;
    element.showPopover?.();

    /** Reposition after viewport changes without scrolling the page or moving focus. */
    function position() {
      if (!target || !element) return;
      const rect = target.getBoundingClientRect();
      const margin = 12;
      const gap = 6;
      const below = innerHeight - rect.bottom - margin - gap;
      const above = rect.top - margin - gap;
      const upwards = placement === 'above' ? above >= 80 || above > below : below < 200 && above > below;
      const widthLimit = placement === 'above' ? Math.min(320, Math.max(200, rect.width)) : innerWidth;
      element.style.maxWidth = `${Math.min(widthLimit, innerWidth - margin * 2)}px`;
      element.style.maxHeight = `${Math.max(80, Math.min(320, upwards ? above : below))}px`;
      if (matchWidth) element.style.width = `${Math.max(rect.width, 200)}px`;
      const width = element.getBoundingClientRect().width;
      const height = element.getBoundingClientRect().height;
      const left = placement === 'above' ? rect.right - width : rect.left;
      element.style.left = `${Math.max(margin, Math.min(left, innerWidth - width - margin))}px`;
      element.style.top = `${upwards ? Math.max(margin, rect.top - height - gap) : rect.bottom + gap}px`;
    }

    position();
    window.addEventListener('resize', position);
    document.addEventListener('scroll', position, true);
    return () => {
      window.removeEventListener('resize', position);
      document.removeEventListener('scroll', position, true);
      if (element.isConnected) element.hidePopover?.();
    };
  }, [anchor, panel, open, matchWidth, placement]);
  return { anchor, panel };
}
