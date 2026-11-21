import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { Modal } from './ui';

afterEach(cleanup);

it('wraps keyboard focus within the confirmation and restores focus on dismissal', () => {
  const opener = document.createElement('button');
  document.body.append(opener);
  opener.focus();
  const close = vi.fn();
  const { unmount } = render(
    <Modal title="Confirm action" close={close}>
      <button>Cancel</button>
      <button disabled>Unavailable</button>
      <button>Confirm</button>
    </Modal>,
  );
  try {
    const dialog = screen.getByRole('dialog', { name: 'Confirm action' });
    const first = within(dialog).getByRole('button', { name: 'Cancel' });
    const last = within(dialog).getByRole('button', { name: 'Confirm' });
    for (const button of [first, last]) {
      // jsdom does not lay out the dialog controls.
      button.getClientRects = () => [{ width: 1, height: 1 }] as unknown as DOMRectList;
    }
    first.focus();
    fireEvent.keyDown(first, { key: 'Tab', shiftKey: true });
    expect(last).toHaveFocus();
    fireEvent.keyDown(last, { key: 'Tab' });
    expect(first).toHaveFocus();
    fireEvent(dialog, new Event('cancel', { cancelable: true }));
    expect(close).toHaveBeenCalledOnce();
    unmount();
    expect(opener).toHaveFocus();
  } finally {
    opener.remove();
  }
});

it('dismisses only a click that starts and ends on the backdrop', () => {
  const close = vi.fn();
  render(
    <Modal title="Review action" close={close}>
      <p>Target details</p>
    </Modal>,
  );
  const dialog = screen.getByRole('dialog', { name: 'Review action' });
  const content = within(dialog).getByText('Target details');
  dialog.getBoundingClientRect = () => new DOMRect(30, 30, 100, 100);
  const outside = { clientX: 5, clientY: 5 };
  fireEvent.pointerDown(content, { isPrimary: true, button: 0 });
  fireEvent.click(dialog, outside);
  fireEvent.pointerDown(dialog, { ...outside, isPrimary: true, button: 0 });
  fireEvent.pointerCancel(dialog);
  fireEvent.click(dialog, outside);
  expect(close).not.toHaveBeenCalled();

  fireEvent.pointerDown(dialog, { ...outside, isPrimary: true, button: 0 });
  fireEvent.click(dialog, outside);
  expect(close).toHaveBeenCalledOnce();
});
