import { fireEvent, within } from '@testing-library/react';

/** Drive rendered options in jsdom; browser checks verify the real popover's visibility. */
export function chooseOption(control: HTMLElement, value: string) {
  fireEvent.click(control);
  const popup = document.getElementById(control.getAttribute('aria-controls') ?? '');
  if (!popup) throw new Error('The selection menu did not open');
  // jsdom does not implement the Popover API's top layer or the production stylesheet.
  const option = within(popup)
    .getAllByRole('option', { hidden: true })
    .find((row) => row.dataset.value === value);
  if (!option || option.getAttribute('aria-disabled') === 'true') throw new Error(`Option is unavailable: ${value}`);
  fireEvent.click(option);
}
