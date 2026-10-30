import { expect, test, type Locator, type Page } from '@playwright/test';

/** Press the native backdrop without activating controls underneath the modal. */
async function clickBackdrop(page: Page, dialog: Locator) {
  const bounds = await dialog.boundingBox();
  if (!bounds) throw new Error('Expected an open dialog');
  const y = bounds.y > 4 ? 2 : bounds.y + bounds.height + 2;
  if ((page.viewportSize()?.width ?? 1440) <= 560) await page.touchscreen.tap(2, y);
  else await page.mouse.click(2, y);
}

for (const kind of ['model', 'status', 'host', 'connection', 'about'] as const) {
  test(`dismisses the ${kind} dialog only on an outside click`, async ({ page }) => {
    await page.goto('/');
    await page.getByRole('textbox').fill('Preserve this draft');
    const requests: string[] = [];
    page.on('request', (request) => {
      if (request.url().includes('/api/v1/')) requests.push(request.url());
    });
    if (kind === 'model') await page.getByRole('button', { name: /Choose model/ }).click();
    else if (kind === 'status') await page.getByRole('button', { name: /^System status/ }).click();
    else if (kind === 'host') await page.getByTitle('Workspace: choose host').click();
    else {
      if ((page.viewportSize()?.width ?? 1440) <= 1100)
        await page.getByRole('button', { name: 'Open host and containers' }).click();
      await page
        .getByRole('button', { name: kind === 'connection' ? 'Connect your API' : 'About this workspace' })
        .click();
    }
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    await dialog.getByRole('heading').first().click();
    const bounds = await dialog.boundingBox();
    if (!bounds) throw new Error('Expected an open dialog');
    await page.mouse.click(bounds.x + 3, bounds.y + 3);
    await expect(dialog).toBeVisible();
    await clickBackdrop(page, dialog);
    await expect(dialog).toHaveCount(0);
    await expect(page.getByRole('textbox')).toHaveValue('Preserve this draft');
    expect(requests).toEqual([]);
  });
}

test('dragging from inside to the backdrop does not dismiss the dialog', async ({ page }) => {
  await page.goto('/');
  const trigger = page.getByRole('button', { name: /Choose model/ });
  await trigger.click();
  const dialog = page.getByRole('dialog');
  const heading = await dialog.getByRole('heading').boundingBox();
  if (!heading) throw new Error('Expected a dialog heading');
  await page.mouse.move(heading.x + 4, heading.y + heading.height / 2);
  await page.mouse.down();
  await page.mouse.move(2, 2, { steps: 5 });
  await page.mouse.up();
  await expect(dialog).toBeVisible();
  await clickBackdrop(page, dialog);
  await expect(dialog).toHaveCount(0);
  await expect(trigger).toBeFocused();
});

test('dismissing action review preserves its prepared ID without executing the action', async ({ page }) => {
  await page.goto('/');
  const trigger = page.getByRole('button', { name: 'Review stop' });
  await trigger.click();
  const dialog = page.getByRole('dialog');
  const action = await dialog.locator('.confirmation-facts code').last().innerText();
  await dialog.getByText('The container will stop serving its workload.').click();
  await expect(dialog).toBeVisible();
  await clickBackdrop(page, dialog);
  await expect(dialog).toHaveCount(0);
  await expect(trigger).toBeFocused();
  await trigger.click();
  await expect(dialog.locator('.confirmation-facts code').last()).toHaveText(action);
  await expect(dialog.getByRole('button', { name: 'Confirm stop' })).toBeVisible();
});
