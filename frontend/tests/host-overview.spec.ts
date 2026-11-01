import { chooseOption } from './helpers/select';
import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { hostAnswer } from './fixtures/host-overview';
import { demoSystemStatus } from '../src/demo';
import type { TurnInput } from '../src/contracts';

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
    const inputs: TurnInput[] = [];
    await page.route('**/api/v1/**', (route) => {
      const request = route.request();
      const url = new URL(request.url());
      expect(request.headers()['authorization']).toBe('Bearer host-overview-browser-token');
      if (url.pathname.endsWith('/hosts')) return route.fulfill({ json: [{ id: 'local', name: 'Test host' }] });
      if (url.pathname.endsWith('/containers')) return route.fulfill({ json: [] });
      if (url.pathname.endsWith('/system/status')) return route.fulfill({ json: demoSystemStatus('local') });
      expect(url.pathname).toBe('/api/v1/chat/turns');
      inputs.push(request.postDataJSON() as TurnInput);
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
    await page.goto('/');
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
    expect(inputs[1]).toMatchObject({ host: 'local', container_id: 'a'.repeat(64) });
    expect(inputs[1]?.session_id).toBeUndefined();
    await expect(page.locator('.query-scope')).toContainText('checkout-api');
    await expect(page.getByRole('textbox')).toHaveValue('Keep this unrelated draft');
    await page.locator('.session-turns summary').click();
    await page.locator('.history-row').first().click();
    await expect(overview).toBeVisible();
    await overview.getByRole('button', { name: 'Docker Compose commerce', exact: true }).click();
    await expect(page.locator('.query-scope')).toContainText('commerce');
    expect(inputs[2]).toMatchObject({ host: 'local', group: { kind: 'compose', name: 'commerce' } });
    expect(inputs[2]?.session_id).toBeUndefined();
    await expect(page.getByRole('textbox')).toHaveValue('Keep this unrelated draft');
    await expect(page.locator('.history-row')).toHaveCount(3);
  });
}

test('keeps long observed names compact and narrows by exact identity within the query limit', async ({ page }) => {
  const answer = hostAnswer();
  const name = `checkout-${'x'.repeat(4087)}`;
  answer.host_overview!.members[0]!.name = name;
  const inputs: TurnInput[] = [];
  await page.route('**/api/v1/**', (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/hosts')) return route.fulfill({ json: [{ id: 'local', name: 'Test host' }] });
    if (url.pathname.endsWith('/containers')) return route.fulfill({ json: [] });
    if (url.pathname.endsWith('/system/status')) return route.fulfill({ json: demoSystemStatus('local') });
    inputs.push(route.request().postDataJSON() as TurnInput);
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
  await page.goto('/');
  await connect(page);
  await page.getByRole('textbox').fill('What happened?');
  await page.getByRole('button', { name: 'Investigate', exact: true }).click();
  const member = page.getByRole('article', { name, exact: true });
  await expect(member).toBeVisible();
  expect((await member.boundingBox())!.height).toBeLessThan(320);
  await member.getByRole('button', { name: 'Investigate container', exact: true }).click();
  await expect(page.locator('.query-scope')).toContainText(name);
  expect(inputs[1]?.container_id).toBe('a'.repeat(64));
  expect(inputs[1]!.query.length).toBeLessThanOrEqual(4000);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
