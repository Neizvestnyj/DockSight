import { expect, type Locator } from '@playwright/test';

/** Choose through the visible listbox, retaining stable fixture IDs across localized labels. */
export async function chooseOption(control: Locator, value: string) {
  const trigger = control.and(control.page().getByRole('combobox'));
  await trigger.click();
  const listId = await trigger.getAttribute('aria-controls');
  expect(listId).toBeTruthy();
  const option = control
    .page()
    .locator(`[id=${JSON.stringify(listId)}]`)
    .getByRole('option')
    .and(control.page().locator(`[data-value=${JSON.stringify(value)}]`));
  await expect(option).not.toHaveAttribute('aria-disabled', 'true');
  await option.click();
}
