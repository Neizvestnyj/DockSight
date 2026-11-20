import { expect, test } from '@playwright/test';

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
