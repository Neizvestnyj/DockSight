import { chooseOption } from './helpers/select';
import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { demoAnswer, demoContainer, demoSystemStatus } from '../src/demo';

/** Connect to intercepted API reads without executing a real runtime operation. */
async function connect(page: Page) {
  if ((page.viewportSize()?.width ?? 1440) <= 560) {
    await page.getByRole('button', { name: 'Open host and containers' }).click();
    await page.getByRole('button', { name: 'Connect your API' }).click();
  } else await page.getByRole('button', { name: 'Connect API', exact: true }).click();
  await page.getByLabel('Bearer token').fill('browser-action-token');
  await page.getByRole('button', { name: 'Connect', exact: true }).click();
  await expect(page.getByTitle('Workspace: choose host')).toContainText('Local test');
}

test('ordinary operations stay in Actions with keyboard dismissal and confirmation focus restored', async ({
  page,
}, info) => {
  await page.goto('/');
  await chooseOption(page.getByRole('combobox', { name: 'Scenario' }), 'running');
  const card = page.getByRole('group', { name: 'Container status', exact: true });
  const trigger = card.locator('.card-actions-menu summary');
  expect((await trigger.boundingBox())!.height).toBeGreaterThanOrEqual(
    (page.viewportSize()?.width ?? 1440) <= 560 ? 44 : 32,
  );
  await expect(card.getByRole('button', { name: 'Review restart' })).toHaveCount(0);
  await expect(card.getByRole('button', { name: 'Review stop' })).toHaveCount(0);
  await trigger.focus();
  await page.keyboard.press('Enter');
  await expect(card.getByRole('button', { name: 'Review restart' })).toBeVisible();
  await expect(card.getByRole('button', { name: 'Review stop' })).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.screenshot({ path: `test-results/${info.project.name}-ordinary-actions.png` });
  await page.keyboard.press('Escape');
  await expect(trigger).toBeFocused();
  await expect(card.getByRole('button', { name: 'Review stop' })).toHaveCount(0);
  await trigger.click();
  await card.getByRole('button', { name: 'Review stop' }).click();
  await expect(page.getByRole('dialog')).toContainText('redis');
  await page.keyboard.press('Escape');
  await expect(trigger).toBeFocused();
  await trigger.click();
  await page.getByRole('heading', { level: 1 }).click();
  await expect(card.getByRole('button', { name: 'Review stop' })).toHaveCount(0);
});

test('an explicit suggestion on a running container remains visible and uses the prepared target', async ({
  page,
}, info) => {
  const answer = demoAnswer('running', 'local');
  const widget = answer.widgets.find((row) => row.widget_type === 'container_status')!;
  const stop = widget.actions.find((action) => action.operation === 'stop')!;
  widget.recommendation = { action_id: stop.id, reason: 'Pause this worker for the requested maintenance window.' };
  const writes: string[] = [];
  await page.route('**/api/v1/**', (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/hosts')) return route.fulfill({ json: [{ id: 'local', name: 'Local test' }] });
    if (url.pathname.endsWith('/system/status')) return route.fulfill({ json: demoSystemStatus('local') });
    if (url.pathname.endsWith('/containers'))
      return route.fulfill({ json: [demoContainer(5, 'local', widget.snapshot.observed_at)] });
    if (url.pathname.endsWith('/chat/turns')) {
      const base = { schema_version: 1, request_id: 'r', turn_id: 't' };
      const events = [
        { ...base, type: 'answer.ready', answer },
        { ...base, type: 'turn.completed' },
      ];
      return route.fulfill({
        contentType: 'text/event-stream',
        body: events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join(''),
      });
    }
    if (url.pathname.includes('/actions/') && route.request().method() === 'GET') {
      const id = url.pathname.split('/').at(-1)!;
      return route.fulfill({ json: widget.actions.find((action) => action.id === id) });
    }
    writes.push(url.pathname);
    return route.abort();
  });
  await page.goto('/');
  await connect(page);
  await page.getByRole('textbox').fill('Check the worker');
  await page.getByRole('button', { name: 'Investigate', exact: true }).click();
  const card = page.getByRole('group', { name: 'Container status', exact: true });
  await expect(card.getByRole('button', { name: 'Review stop' })).toBeVisible();
  await expect(card.getByRole('button', { name: 'Review restart' })).toHaveCount(0);
  await expect(card).toContainText('Suggested by model');
  await expect(card).toContainText('Pause this worker for the requested maintenance window.');
  await card.getByRole('button', { name: 'Supporting evidence' }).click();
  await expect(page.getByRole('region', { name: 'Evidence observation' })).toBeFocused();
  await card.scrollIntoViewIfNeeded();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.screenshot({ path: `test-results/${info.project.name}-recommended-action.png` });
  await card.getByRole('button', { name: 'Review stop' }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toContainText(stop.container_id);
  await expect(dialog).toContainText(stop.id);
  await page.keyboard.press('Escape');
  expect(writes).toEqual([]);
});
