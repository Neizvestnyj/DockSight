import { expect, test } from '@playwright/test';
import { openDemo } from './helpers/demo';
import { savedApi } from './helpers/saved-api';
import { chooseOption } from './helpers/select';

test('opens the example explicitly and exits Demo with the keyboard', async ({ page }) => {
  await openDemo(page);
  await expect(page.getByRole('heading', { name: 'Start an investigation' })).toBeVisible();
  const host = page.getByTitle('Workspace: choose host').getByText('Demo host / EU');
  await expect(host).toBeVisible();
  expect(await host.evaluate((label) => label.scrollWidth <= label.clientWidth)).toBe(true);

  const example = page.getByRole('button', { name: 'View example' });
  await example.press('Enter');
  await expect(page.getByRole('heading', { name: 'Why does payments-api keep restarting?' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Container investigation', exact: true })).toBeFocused();

  await page.getByRole('button', { name: 'Exit Demo' }).press('Enter');
  await expect(page.getByRole('button', { name: 'Connect API', exact: true })).toBeVisible();
  const demo = page.getByRole('button', { name: 'Explore Demo' });
  await expect(demo).toBeFocused();
  await demo.press('Enter');
  await expect(page.getByRole('heading', { name: 'Start an investigation' })).toBeVisible();
});

test('leaves Demo from an existing API workspace without revoking the API session', async ({ page }) => {
  const api = await savedApi(page);
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Archived question 1' })).toBeVisible();
  if ((page.viewportSize()?.width ?? 1440) <= 1100)
    await page.getByRole('button', { name: 'Open host and containers' }).click();
  await page.getByRole('button', { name: 'Return to demo' }).click();
  await expect(page.getByRole('heading', { name: 'Start an investigation' })).toBeVisible();
  await page.getByRole('button', { name: 'Exit Demo' }).click();
  await expect(page.getByRole('button', { name: 'Explore Demo' })).toBeFocused();
  expect(api.signedIn).toBe(true);
});

test('explains API connection failures before recovery reaches sign-in', async ({ page }) => {
  let attempts = 0;
  await page.route('**/api/v1/auth/session', (route) => {
    attempts++;
    if (attempts === 1) return route.fulfill({ status: 502 });
    if (attempts === 2) return route.abort('failed');
    return route.fulfill({ status: 401, json: { code: 'unauthorized', message: 'Unauthorized' } });
  });
  await page.goto('/');
  const retry = page.getByRole('button', { name: 'Retry connection', exact: true });
  await expect(page.getByRole('heading', { name: 'Could not connect to the DockSight API.' })).toBeVisible();
  await expect(page.getByRole('status')).toContainText('Demo works without the API.');
  await retry.click();
  await expect(page.getByRole('heading', { name: 'Could not connect to the DockSight API.' })).toBeVisible();
  await retry.click();
  await expect(page.getByRole('heading', { name: 'Sign in to DockSight' })).toBeVisible();
  await expect(page.getByRole('status')).toHaveText('Your session is no longer valid. Sign in again.');
  await expect(retry).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Connect API', exact: true })).toBeEnabled();
  await chooseOption(page.getByRole('combobox', { name: 'Language' }), 'ru');
  await expect(page.getByRole('status')).toHaveText('Сессия недействительна. Войдите снова.');
  expect(attempts).toBe(3);
});

test('restores the workspace when the connection retry succeeds', async ({ page }) => {
  await savedApi(page);
  await page.route('**/api/v1/auth/session', (route) => route.abort('failed'), { times: 1 });
  await page.goto('/');
  await page.getByRole('button', { name: 'Retry connection', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Archived question 1' })).toBeVisible();
  await expect(page.getByText('Your session is no longer valid. Sign in again.')).toHaveCount(0);
});

for (const [code, hint] of [
  ['origin_not_allowed', 'DOCKSIGHT_BROWSER_ORIGIN'],
  ['insecure_browser_origin', 'DOCKSIGHT_COOKIE_SECURE=false'],
] as const) {
  test(`explains ${code} for the public preview API`, async ({ page }, info) => {
    await page.route('**/api/v1/auth/session', (route) =>
      route.fulfill({ status: 401, json: { code: 'unauthorized', message: 'Unauthorized' } }),
    );
    await page.route('**/api/v1/auth/login', (route) =>
      route.fulfill({ status: 403, json: { code, message: 'Browser login was rejected' } }),
    );
    await page.goto('/');
    await expect(page.getByText('Your session is no longer valid. Sign in again.')).toHaveCount(0);
    await page.getByRole('button', { name: 'Connect API', exact: true }).click();
    const address = page.getByLabel('API base URL');
    await expect(address).toHaveValue(`${new URL(page.url()).origin}/api/v1`);
    await expect(address).toHaveAttribute('placeholder', '/api/v1');
    if (code === 'origin_not_allowed') {
      const box = await address.boundingBox();
      await address.click();
      await page.getByRole('dialog').screenshot({ path: info.outputPath('connection-focus.png') });
      await expect(address).toHaveCSS('outline-offset', '-2px');
      await expect(address).toHaveCSS('outline-width', '2px');
      expect(await address.boundingBox()).toEqual(box);
      await address.press('Tab');
      await expect(page.getByLabel('Bearer token')).toBeFocused();
      await expect(page.getByLabel('Bearer token')).toHaveCSS('outline-offset', '-2px');
    }
    if (code === 'insecure_browser_origin') await address.fill('/api/v1');
    await page.getByLabel('Bearer token').fill('test-only-connection-token');
    await page.getByRole('button', { name: 'Connect', exact: true }).click();
    await expect(page.getByRole('alert')).toContainText(hint);
    await expect(page.getByRole('alert')).not.toContainText('Check the API endpoint.');
    await expect(page.getByLabel('Bearer token')).toHaveValue('');
  });
}
