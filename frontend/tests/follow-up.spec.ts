import { routeSavedApi } from './helpers/saved-server';
import { openDemo } from './helpers/demo';
import { expect, test } from '@playwright/test';
import { DemoClient, demoAnswer, demoContainer, demoSystemStatus } from '../src/demo';
import { demoGroupAnswer } from '../src/demoGroup';
import type { StartTurn } from '../src/investigation-contracts';

test('continues a group diagnosis in one session, retains earlier evidence, and starts fresh from Diagnostics', async ({
  page,
}) => {
  const inputs: StartTurn[] = [];
  const session = '62f9fcc6-583e-4b3d-9678-10ffea8ae671';
  const rows = Array.from({ length: 6 }, (_, index) => demoContainer(index, 'local', '2026-10-30T10:00:00Z'));
  const groups = await new DemoClient().stacks('demo-eu', 'compose', new AbortController().signal);
  const first = demoGroupAnswer(demoAnswer('dependency', 'local'), rows, groups[0]!);
  const second = demoAnswer('dependency', 'local');
  const status = second.widgets.find((row) => row.widget_type === 'container_status')!;
  status.snapshot.name = 'vintoria-db';
  status.snapshot.compose_project = 'vintoria-db';
  second.summary = 'The dependency container exited. The observations do not establish the underlying cause.';
  second.widgets = second.widgets.filter((row) => row.widget_type !== 'compose_stack');
  await routeSavedApi(page, (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/hosts')) return route.fulfill({ json: [{ id: 'local', name: 'Test host' }] });
    if (url.pathname.endsWith('/containers')) return route.fulfill({ json: rows });
    if (url.pathname.endsWith('/system/status')) return route.fulfill({ json: demoSystemStatus('local') });
    expect(url.pathname.endsWith('/turns')).toBe(true);
    inputs.push(route.request().postDataJSON() as StartTurn);
    const envelope = { schema_version: 1, request_id: `r-${inputs.length}`, turn_id: `t-${inputs.length}` };
    return route.fulfill({
      contentType: 'text/event-stream',
      body: [
        { ...envelope, type: 'turn.started', session_id: session },
        { ...envelope, type: 'answer.ready', answer: inputs.length === 1 ? first : second },
        { ...envelope, type: 'turn.completed' },
      ]
        .map((event) => `data: ${JSON.stringify(event)}\n\n`)
        .join(''),
    });
  });
  await openDemo(page);
  if ((page.viewportSize()?.width ?? 1440) <= 560) {
    await page.getByRole('button', { name: 'Open host and containers' }).click();
    await page.getByRole('button', { name: 'Connect your API' }).click();
  } else await page.getByRole('button', { name: 'Connect API', exact: true }).click();
  await page.getByLabel('Bearer token').fill('follow-up-browser-token');
  await page.getByRole('button', { name: 'Connect', exact: true }).click();
  await expect(page.locator('.composer-foot')).toContainText('local');
  await page.getByRole('textbox').fill('What happened to commerce?');
  await page.getByRole('button', { name: 'Investigate', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Group observations', exact: true })).toBeVisible();
  const followup = 'Maybe the database is stopped? Check container vintoria-db.';
  await page.getByRole('textbox').fill(followup);
  await page.getByRole('button', { name: 'Investigate', exact: true }).click();
  await expect(page.locator('.conclusion > p').first()).toHaveText(second.summary);
  expect(inputs[1]).toMatchObject({ kind: 'question', query: followup, target: null });
  await expect(page.getByRole('heading', { name: 'vintoria-db', exact: true })).toBeVisible();
  await page.locator('.session-turns summary').click();
  await page.locator('.history-row').first().click();
  await expect(page.getByRole('region', { name: 'Group observations', exact: true })).toContainText('commerce');
  await expect(page.locator('.conclusion > p').first()).toHaveText(first.summary);
  if ((page.viewportSize()?.width ?? 1440) <= 1100)
    await page.getByRole('button', { name: 'Open host and containers' }).click();
  await page.locator('.workspace-nav:visible').getByRole('button', { name: 'Diagnostics', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Start an investigation' })).toBeVisible();
  await page.getByRole('textbox').fill('Check the dependency again.');
  await page.getByRole('button', { name: 'Investigate', exact: true }).click();
  await expect(page.locator('.conclusion > p').first()).toHaveText(second.summary);
  expect(inputs[2]).toMatchObject({ kind: 'question', query: 'Check the dependency again.', target: null });
});
