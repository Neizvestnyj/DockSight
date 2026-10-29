import { expect, test, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { DemoClient, demoAnswer, demoContainer, demoSystemStatus } from '../src/demo';
import { demoGroupAnswer } from '../src/demoGroup';
import type { TurnInput } from '../src/contracts';

/** Locate optional diagnostic scope in the main workspace on every viewport. */
async function openScope(page: Page) {
  return page.getByRole('combobox', { name: 'Investigation scope' });
}

test('diagnoses the whole Compose project and preserves its historical group observations', async ({ page }, info) => {
  await page.goto('/');
  await page.getByRole('combobox', { name: 'Language' }).selectOption('en');
  await page.getByRole('textbox').fill('Keep this follow-up draft');
  await (await openScope(page)).selectOption('compose');
  await page.getByRole('combobox', { name: 'Group', exact: true }).filter({ visible: true }).selectOption('commerce');
  await page.getByRole('button', { name: 'Diagnose group' }).filter({ visible: true }).click();
  const report = page.getByRole('region', { name: 'Group observations' });
  await expect(report).toBeVisible();
  await expect(report.locator('.group-member')).toHaveCount(6);
  await expect(report.getByText('checkout-api', { exact: true })).toBeVisible();
  await expect(report.getByText('report-worker', { exact: true })).toBeVisible();
  await expect(report).toContainText('Problem containers with logs: 1 / 5');
  await expect(page.getByText('Immediate failure', { exact: true })).toBeVisible();
  await expect(page.getByText('Still unknown', { exact: true })).toBeVisible();
  await expect(page.getByRole('textbox')).toHaveValue('Keep this follow-up draft');
  await report.getByRole('button', { name: 'Logs', exact: true }).click();
  await expect(page.getByLabel('Evidence observation')).toBeFocused();
  await expect(page.getByLabel('Evidence observation')).toContainText('Docker logs');
  await report.scrollIntoViewIfNeeded();
  await page.screenshot({ path: `test-results/${info.project.name}-compose-group.png` });
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await (await openScope(page)).selectOption('all');
  await expect(report.locator('.group-member')).toHaveCount(6);
  await expect(page.getByRole('textbox')).toHaveValue('Keep this follow-up draft');
  await page.getByRole('combobox', { name: 'Language' }).selectOption('ru');
  await expect(page.getByText('Непосредственная причина сбоя', { exact: true })).toBeVisible();
  await expect(page.getByText('Пока неизвестно', { exact: true })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Наблюдения группы' }).locator('.group-member')).toHaveCount(6);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('keeps empty Swarm discovery explicit without calling the model', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('combobox', { name: 'Language' }).selectOption('en');
  await (await openScope(page)).selectOption('swarm');
  await expect(page.getByText('No groups of this kind were returned.').filter({ visible: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Diagnose group' }).filter({ visible: true })).toBeDisabled();
});

test('sends an authenticated exact group target and retries its original scope after a filter change', async ({
  page,
}, info) => {
  const rows = Array.from({ length: 6 }, (_, index) => demoContainer(index, 'test-host', '2026-10-28T10:00:00Z'));
  const groups = await new DemoClient().stacks('demo-eu', 'compose', new AbortController().signal);
  const answer = demoGroupAnswer(demoAnswer('dependency', 'test-host'), rows, groups[0]!);
  const second = rows[3]!;
  const state = answer.evidence.find((row) => row.kind === 'container')!;
  const log = answer.evidence.find((row) => row.kind === 'logs')!;
  const status = answer.widgets.find((row) => row.widget_type === 'container_status')!;
  const logCard = answer.widgets.find((row) => row.widget_type === 'log_anomalies')!;
  const entries = [{ timestamp: '2026-10-28T10:00:00Z', message: 'Migration failed: database connection refused' }];
  answer.evidence.push(
    { ...state, id: 'second-state', container_id: second.id, data: { name: second.name, state: second.state } },
    { ...log, id: 'second-logs', container_id: second.id, data: { entries, truncated: false } },
  );
  answer.widgets.push(
    { ...status, snapshot: second, evidence_ids: ['second-state'], actions: [], recommendation: null },
    { ...logCard, container_id: second.id, evidence_ids: ['second-logs'], logs: { entries, truncated: false } },
  );
  const inputs: TurnInput[] = [];
  await page.route('**/api/v1/**', (route) => {
    const request = route.request();
    expect(request.headers()['authorization']).toBe('Bearer browser-test-token');
    const url = new URL(request.url());
    if (url.pathname.endsWith('/hosts')) return route.fulfill({ json: [{ id: 'test-host', name: 'Test host' }] });
    if (url.pathname.endsWith('/system/status'))
      return route.fulfill({ json: demoSystemStatus(url.searchParams.get('host')) });
    if (url.pathname.endsWith('/containers')) return route.fulfill({ json: rows });
    if (url.pathname.endsWith('/stacks')) {
      expect(url.searchParams.get('kind')).toBe('compose');
      return route.fulfill({ json: groups });
    }
    expect(url.pathname).toBe('/api/v1/chat/turns');
    inputs.push(request.postDataJSON() as TurnInput);
    const envelope = { schema_version: 1, request_id: 'r', turn_id: `t-${inputs.length}` };
    const events = [
      { ...envelope, type: 'turn.started', session_id: '4a59a145-0037-4934-92e0-f422105583b9' },
      ...(inputs.length === 1
        ? [{ ...envelope, type: 'turn.failed', code: 'model_timeout', message: 'Retry this group' }]
        : [
            { ...envelope, type: 'answer.ready', answer },
            { ...envelope, type: 'turn.completed' },
          ]),
    ];
    return route.fulfill({
      contentType: 'text/event-stream',
      body: events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join(''),
    });
  });
  await page.goto('/');
  await page.getByRole('combobox', { name: 'Language' }).selectOption('en');
  if ((page.viewportSize()?.width ?? 1440) <= 560) {
    await page.getByRole('button', { name: 'Open host and containers' }).click();
    await page.getByRole('button', { name: 'Connect your API' }).click();
  } else await page.getByRole('button', { name: 'Connect API', exact: true }).click();
  await page.getByLabel('Bearer token').fill('browser-test-token');
  await page.getByRole('button', { name: 'Connect', exact: true }).click();
  await expect(page.locator('.composer-foot')).toContainText('test-host');
  await (await openScope(page)).selectOption('compose');
  await page.getByRole('combobox', { name: 'Group', exact: true }).filter({ visible: true }).selectOption('commerce');
  expect(inputs).toHaveLength(0);
  await page.getByRole('button', { name: 'Diagnose group' }).filter({ visible: true }).click();
  await expect(page.getByRole('button', { name: 'Retry diagnosis' })).toBeVisible();
  expect(inputs[0]?.group).toEqual({ kind: 'compose', name: 'commerce' });
  await (await openScope(page)).selectOption('all');
  await page.getByRole('button', { name: 'Retry diagnosis' }).click();
  await expect(page.getByRole('region', { name: 'Group observations' })).toBeVisible();
  expect(inputs).toHaveLength(2);
  expect(inputs[1]?.group).toEqual(inputs[0]?.group);
  await expect(page.getByRole('region', { name: 'Container status', exact: true })).toHaveCount(2);
  await expect(page.getByRole('region', { name: 'Container logs', exact: true })).toHaveCount(2);
  const sources = page.getByRole('region', { name: 'Observation sources' });
  const member = sources.getByRole('group', { name: 'migration-runner', exact: true });
  await member.getByRole('button', { name: /^Logs/ }).click();
  await expect(page.getByRole('region', { name: 'Evidence observation' })).toContainText('migration-runner');
  await expect(page.getByRole('region', { name: 'Evidence observation' })).toBeFocused();
  await sources.scrollIntoViewIfNeeded();
  await page.screenshot({ path: `test-results/${info.project.name}-group-sources.png` });
});

test('keeps Russian group controls inside the workspace with an accessible consistent action', async ({
  page,
}, info) => {
  await page.goto('/');
  await page.getByRole('combobox', { name: 'Language' }).selectOption('ru');
  const scope = page.getByRole('region', { name: 'Область диагностики' });
  await scope.getByRole('combobox', { name: 'Область диагностики' }).selectOption('compose');
  await scope.getByRole('combobox', { name: 'Группа', exact: true }).selectOption('commerce');
  const button = scope.getByRole('button', { name: 'Диагностировать группу' });
  await expect(button).toBeEnabled();
  const frame = (await scope.boundingBox())!;
  const control = (await button.boundingBox())!;
  expect(control.x).toBeGreaterThanOrEqual(frame.x);
  expect(control.x + control.width).toBeLessThanOrEqual(frame.x + frame.width + 1);
  expect(await button.locator('svg').count()).toBe(1);
  await button.focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('region', { name: 'Наблюдения группы' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await scope.scrollIntoViewIfNeeded();
  await page.screenshot({ path: `test-results/${info.project.name}-group-controls-ru.png` });
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});
