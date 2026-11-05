import { routeSavedApi } from './helpers/saved-server';
import { openDemo } from './helpers/demo';
import { chooseOption } from './helpers/select';
import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { hostAnswer } from './fixtures/host-overview';
import { demoContainer, demoSystemStatus } from '../src/demo';
import type { StartTurn } from '../src/investigation-contracts';

/** Connect to the test's isolated intercepted API on desktop and mobile. */
async function connect(page: Page) {
  if ((page.viewportSize()?.width ?? 1440) <= 560) {
    await page.getByRole('button', { name: 'Open host and containers' }).click();
    await page.getByRole('button', { name: 'Connect your API' }).click();
  } else await page.getByRole('button', { name: 'Connect API', exact: true }).click();
  await page.getByLabel('Bearer token').fill('host-overview-browser-token');
  await page.getByRole('button', { name: 'Connect', exact: true }).click();
  await expect(page.locator('.composer-foot')).toContainText('local');
}

for (const locale of ['en', 'ru'] as const) {
  test(`shows bounded host evidence and narrows explicitly without losing draft or history (${locale})`, async ({
    page,
  }, info) => {
    const answer = hostAnswer();
    const inputs: StartTurn[] = [];
    await routeSavedApi(page, (route) => {
      const request = route.request();
      const url = new URL(request.url());
      expect(request.headers()['authorization']).toBeUndefined();
      if (url.pathname.endsWith('/hosts')) return route.fulfill({ json: [{ id: 'local', name: 'Test host' }] });
      if (url.pathname.endsWith('/containers')) return route.fulfill({ json: [] });
      if (url.pathname.endsWith(`/${'a'.repeat(64)}`))
        return route.fulfill({
          json: { ...demoContainer(0, 'local', new Date().toISOString()), id: 'a'.repeat(64), name: 'checkout-api' },
        });
      if (url.pathname.endsWith('/system/status')) return route.fulfill({ json: demoSystemStatus('local') });
      expect(url.pathname.endsWith('/turns')).toBe(true);
      inputs.push(request.postDataJSON() as StartTurn);
      const base = { schema_version: 1, request_id: `r${inputs.length}`, turn_id: `t${inputs.length}` };
      return route.fulfill({
        contentType: 'text/event-stream',
        body: [
          { ...base, type: 'turn.started', session_id: '62f9fcc6-583e-4b3d-9678-10ffea8ae671' },
          { ...base, type: 'tool.started', tool: 'inspect_host' },
          { ...base, type: 'tool.completed', tool: 'inspect_host', ok: true },
          {
            ...base,
            type: 'answer.ready',
            answer:
              inputs.length === 1
                ? answer
                : {
                    schema_version: 1,
                    summary: 'The selected resource needs more evidence.',
                    uncertain: true,
                    widgets: [],
                    evidence: [],
                  },
          },
          { ...base, type: 'turn.completed' },
        ]
          .map((event) => `data: ${JSON.stringify(event)}\n\n`)
          .join(''),
      });
    });
    await openDemo(page);
    await connect(page);
    await page.getByRole('textbox').fill('What happened?');
    await page.getByRole('button', { name: 'Investigate', exact: true }).click();
    let overview = page.getByRole('region', { name: 'Host overview', exact: true });
    await expect(overview.getByRole('article')).toHaveCount(5);
    await expect(page.getByRole('region', { name: 'Group clarification' })).toHaveCount(0);
    await expect(page.getByRole('status', { name: 'Diagnostic progress' })).toContainText(
      'Inspecting host observations',
    );
    await expect(overview.locator('dl')).toContainText('7');
    await expect(overview.getByText('Unhealthy')).toBeVisible();
    await expect(overview.getByText('Collection limit reached')).toHaveCount(2);
    await expect(overview.getByText('Log read failed')).toBeVisible();
    await expect(overview.getByText('swarm_unavailable')).toBeVisible();
    await overview.getByRole('button', { name: 'Source', exact: true }).click();
    await expect(page.getByRole('region', { name: 'Evidence observation' })).toBeFocused();
    await expect(page.getByRole('region', { name: 'Evidence observation' })).toContainText('Docker host inventory');
    await page.getByRole('textbox').fill('Keep this unrelated draft');
    await chooseOption(page.getByRole('combobox', { name: 'Language' }), locale);
    overview = page.getByRole('region', { name: locale === 'ru' ? 'Обзор хоста' : 'Host overview', exact: true });
    await expect(overview.getByText(locale === 'ru' ? 'Сбой' : 'Unhealthy')).toBeVisible();
    await expect(page.locator('.conclusion')).toContainText(answer.summary);
    await overview.scrollIntoViewIfNeeded();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
    await overview
      .getByRole('heading', { name: locale === 'ru' ? 'Обзор хоста' : 'Host overview', exact: true })
      .click();
    await page.screenshot({ path: `test-results/${info.project.name}-host-overview-${locale}.png`, fullPage: true });
    await overview.screenshot({ path: `test-results/${info.project.name}-host-overview-panel-${locale}.png` });
    const investigate = overview.getByRole('article', { name: 'checkout-api', exact: true }).getByRole('button', {
      name: locale === 'ru' ? 'Исследовать контейнер' : 'Investigate container',
      exact: true,
    });
    await investigate.focus();
    await page.keyboard.press('Enter');
    await expect(page.locator('.conclusion')).toContainText('The selected resource needs more evidence.');
    expect(inputs[1]).toMatchObject({ kind: 'question', target: { kind: 'container', id: 'a'.repeat(64) } });
    expect(inputs[1]).not.toHaveProperty('session_id');
    await expect(page.locator('.query-scope')).toContainText('checkout-api');
    await expect(page.getByRole('textbox')).toHaveValue('Keep this unrelated draft');
    await page.locator('.session-turns summary').click();
    await page.locator('.history-row').first().click();
    await expect(overview).toBeVisible();
    await overview.getByRole('button', { name: 'Docker Compose commerce', exact: true }).click();
    await expect(page.locator('.query-scope')).toContainText('commerce');
    expect(inputs[2]).toMatchObject({ kind: 'question', target: { kind: 'compose', name: 'commerce' } });
    expect(inputs[2]).not.toHaveProperty('session_id');
    await expect(page.getByRole('textbox')).toHaveValue('Keep this unrelated draft');
    await expect(page.locator('.history-row')).toHaveCount(3);
  });
}

test('keeps long observed names compact and narrows by exact identity within the query limit', async ({ page }) => {
  const answer = hostAnswer();
  const name = `checkout-${'x'.repeat(4087)}`;
  answer.host_overview!.members[0]!.name = name;
  const inputs: StartTurn[] = [];
  await routeSavedApi(page, (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/hosts')) return route.fulfill({ json: [{ id: 'local', name: 'Test host' }] });
    if (url.pathname.endsWith('/containers')) return route.fulfill({ json: [] });
    if (url.pathname.endsWith(`/${'a'.repeat(64)}`))
      return route.fulfill({
        json: { ...demoContainer(0, 'local', new Date().toISOString()), id: 'a'.repeat(64), name },
      });
    if (url.pathname.endsWith('/system/status')) return route.fulfill({ json: demoSystemStatus('local') });
    inputs.push(route.request().postDataJSON() as StartTurn);
    const base = { schema_version: 1, request_id: 'r', turn_id: 't' };
    return route.fulfill({
      contentType: 'text/event-stream',
      body: [
        { ...base, type: 'answer.ready', answer },
        { ...base, type: 'turn.completed' },
      ]
        .map((event) => `data: ${JSON.stringify(event)}\n\n`)
        .join(''),
    });
  });
  await openDemo(page);
  await connect(page);
  await page.getByRole('textbox').fill('What happened?');
  await page.getByRole('button', { name: 'Investigate', exact: true }).click();
  const member = page.getByRole('article', { name, exact: true });
  await expect(member).toBeVisible();
  expect((await member.boundingBox())!.height).toBeLessThan(320);
  await member.getByRole('button', { name: 'Investigate container', exact: true }).click();
  await expect(page.locator('.query-scope')).toContainText(name.slice(0, 256));
  expect(inputs[1]?.target).toMatchObject({ kind: 'container', id: 'a'.repeat(64) });
  if (inputs[1]?.kind !== 'question') throw new Error('Expected a container question');
  expect(inputs[1].query.length).toBeLessThanOrEqual(4000);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
