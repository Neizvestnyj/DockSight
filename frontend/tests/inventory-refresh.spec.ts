import { routeSavedApi } from './helpers/saved-server';
import { openDemo } from './helpers/demo';
import { expect, test } from '@playwright/test';
import { demoContainer, demoSystemStatus } from '../src/demo';

test('updates inventory and exact selected state while preserving a draft across deletion', async ({ page }, info) => {
  let container = demoContainer(0, 'test-host', '2026-10-28T07:00:00Z');
  let rows = [container];
  let removed = false;
  let holdInventory = false;
  let release = () => {};
  const inventoryGate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const paths: string[] = [];
  await routeSavedApi(page, async (route) => {
    const url = new URL(route.request().url());
    paths.push(url.pathname);
    expect(route.request().headers()['authorization']).toBeUndefined();
    if (url.pathname.endsWith('/hosts')) return route.fulfill({ json: [{ id: 'test-host', name: 'Test host' }] });
    if (url.pathname.endsWith('/system/status'))
      return route.fulfill({ json: demoSystemStatus(url.searchParams.get('host')) });
    if (url.pathname.endsWith('/containers')) {
      if (holdInventory) await inventoryGate;
      return route.fulfill({ json: rows });
    }
    if (url.pathname.endsWith('/logs')) return route.fulfill({ json: { entries: [], truncated: false } });
    if (url.pathname.endsWith('/stats'))
      return route.fulfill({ json: { cpu_percent: 1, memory_usage_bytes: 100, memory_limit_bytes: 200 } });
    return removed
      ? route.fulfill({ status: 404, json: { code: 'container_not_found', message: 'Container not found' } })
      : route.fulfill({ json: container });
  });
  await page.clock.install();
  await openDemo(page);
  if ((page.viewportSize()?.width ?? 1440) <= 560) {
    await page.getByRole('button', { name: 'Open host and containers' }).click();
    await page.getByRole('button', { name: 'Connect your API' }).click();
  } else await page.getByRole('button', { name: 'Connect API', exact: true }).click();
  await page.getByLabel('Bearer token').fill('browser-test-token');
  await page.getByRole('button', { name: 'Connect', exact: true }).click();
  await expect(page.locator('.composer-foot')).toContainText('test-host');
  const draft = page.getByRole('textbox', { name: 'Ask DockSight', exact: true });
  await draft.fill('Keep this investigation');
  await expect(page.locator('.sidebar [title="payments-api"]')).toHaveCount(1);
  rows = [container, { ...demoContainer(1, 'test-host', '2026-10-28T07:00:10Z'), name: 'new-worker' }];
  holdInventory = true;
  await page.clock.runFor(10_000);
  const refresh = page
    .locator('.sidebar')
    .getByRole('button', { name: 'Refresh container inventory', includeHidden: true });
  try {
    await expect(refresh).toHaveAttribute('aria-busy', 'true');
    await expect(refresh.locator('svg')).toHaveCSS('animation-name', 'spin');
    await expect(page.locator('.sidebar [title="payments-api"]')).toHaveCount(1);
  } finally {
    holdInventory = false;
    release();
  }
  await expect(page.locator('.sidebar [title="new-worker"]')).toHaveCount(1);
  await expect(refresh).toHaveAttribute('aria-busy', 'false');
  if ((page.viewportSize()?.width ?? 1440) <= 1100)
    await page.getByRole('button', { name: 'Open host and containers' }).click();
  await page.getByTitle('payments-api', { exact: true }).last().click();
  const facts = page.getByRole('region', { name: 'Container facts' });
  await expect(facts.getByRole('button', { name: 'Refresh data' })).toBeEnabled();
  container = { ...container, state: 'exited', observed_at: '2026-10-28T07:00:20Z' };
  rows = [container];
  await page.clock.runFor(10_000);
  await expect(facts.getByRole('region', { name: 'Container status', exact: true })).toContainText('exited');
  rows = [{ ...container, id: 'f'.repeat(64), state: 'running' }];
  removed = true;
  await page.clock.runFor(10_000);
  await expect(facts).toContainText('This container no longer exists on the selected host.');
  await expect(facts).toContainText('1'.repeat(64));
  await expect(facts).not.toContainText('f'.repeat(64));
  await expect(facts.getByRole('button', { name: 'Diagnose' })).toBeDisabled();
  await page.screenshot({ path: `test-results/${info.project.name}-removed-container.png`, fullPage: true });
  await facts.getByRole('button', { name: 'Back to investigation' }).click();
  await expect(draft).toHaveValue('Keep this investigation');
  expect(paths.filter((path) => path.endsWith('/logs'))).toHaveLength(1);
  expect(paths.filter((path) => path.endsWith('/stats'))).toHaveLength(1);
  expect(paths.some((path) => path.includes('/chat/') || path.includes('/actions'))).toBe(false);
});
