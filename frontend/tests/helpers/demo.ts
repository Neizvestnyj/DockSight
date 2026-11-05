import { expect, type Page } from '@playwright/test';

/** Choose simulated data explicitly while isolating bootstrap from unrelated API fixtures. */
export async function openDemo(page: Page) {
  await page.route('**/api/v1/auth/session', (route) =>
    route.fulfill({ status: 401, json: { code: 'unauthorized', message: 'Sign in' } }),
  );
  await page.goto('/');
  const entry = page.getByRole('button', { name: /Explore Demo|Открыть демо/ });
  await expect(entry).toBeVisible();
  await entry.click();
}
