import { expect, type Locator } from '@playwright/test';

/** Wait for listbox rendering, retaining stable fixture IDs across localized labels. */
export async function chooseOption(control: Locator, value: string) {
  const trigger = control.and(control.page().getByRole('combobox'));
  await trigger.click();
  await expect(trigger).toHaveAttribute('aria-controls', /\S+/);
  const listId = await trigger.getAttribute('aria-controls');
  const option = control
    .page()
    .locator(`[id=${JSON.stringify(listId)}]`)
    .getByRole('option')
    .and(control.page().locator(`[data-value=${JSON.stringify(value)}]`));
  await expect(option).not.toHaveAttribute('aria-disabled', 'true');
  await option.click();
}
