import { expect, test, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { demoAnswer, demoContainer, demoSystemStatus } from '../src/demo';
import type { TurnInput } from '../src/contracts';

/** Reach the same container from a persistent sidebar or the mobile navigation sheet. */
async function chooseContainer(page: Page, name: string, russian = false) {
  if ((page.viewportSize()?.width ?? 1440) <= 1100)
    await page
      .getByRole('button', { name: russian ? 'Открыть хосты и контейнеры' : 'Open host and containers' })
      .click();
  await page.getByTitle(name, { exact: true }).filter({ visible: true }).click();
}

/** Connect only to the test's intercepted API, never to a model provider or Docker host. */
async function connectApi(page: Page) {
  if ((page.viewportSize()?.width ?? 1440) <= 560) {
    await page.getByRole('button', { name: 'Open host and containers' }).click();
    await page.getByRole('button', { name: 'Connect your API' }).click();
  } else await page.getByRole('button', { name: 'Connect API', exact: true }).click();
  await page.getByLabel('Bearer token').fill('browser-test-token');
  await page.getByRole('button', { name: 'Connect', exact: true }).click();
  await expect(page.locator('.composer-foot')).toContainText('test-host');
}

test('reads and refreshes facts without LLM calls, then diagnoses in a separate session', async ({ page }) => {
  const snapshot = demoContainer(0, 'test-host', '2026-10-20T09:00:00Z');
  const answer = demoAnswer('crash_loop', snapshot.host);
  const status = answer.widgets.find((row) => row.widget_type === 'container_status')!;
  status.snapshot = snapshot;
  const requests: TurnInput[] = [];
  let reads = 0;
  await page.route('**/api/v1/**', (route) => {
    const request = route.request();
    expect(request.headers()['authorization']).toBe('Bearer browser-test-token');
    const path = new URL(request.url()).pathname;
    if (path.endsWith('/system/status'))
      return route.fulfill({ json: demoSystemStatus(new URL(request.url()).searchParams.get('host')) });
    if (path.endsWith('/hosts')) return route.fulfill({ json: [{ id: snapshot.host, name: 'Test host' }] });
    if (path.endsWith('/containers')) return route.fulfill({ json: [snapshot] });
    if (path.endsWith('/stats')) return route.fulfill({ json: { ...snapshot.metrics, cpu_percent: 0 } });
    if (path.endsWith('/logs')) return route.fulfill({ json: { entries: [], truncated: false } });
    if (path.endsWith(`/${snapshot.id}`)) {
      reads++;
      return route.fulfill({ json: { ...snapshot, restart_count: 19, observed_at: '2026-10-27T12:00:00Z' } });
    }
    expect(path).toBe('/api/v1/chat/turns');
    requests.push(request.postDataJSON() as TurnInput);
    const envelope = { schema_version: 1, request_id: 'r', turn_id: `t-${requests.length}` };
    const events = [
      { ...envelope, type: 'turn.started', session_id: '4a59a145-0037-4934-92e0-f422105583b9' },
      { ...envelope, type: 'answer.ready', answer },
      { ...envelope, type: 'turn.completed' },
    ];
    return route.fulfill({
      contentType: 'text/event-stream',
      body: events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join(''),
    });
  });
  await page.goto('/');
  await connectApi(page);
  await page.getByRole('textbox').fill('Original investigation');
  await page.getByRole('button', { name: 'Investigate', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Review stop' })).toBeVisible();
  await chooseContainer(page, snapshot.name);
  const facts = page.getByRole('region', { name: 'Container facts', exact: true });
  await expect(facts.getByText('APP_ENV')).toBeVisible();
  await expect(facts.getByText('0.0%')).toBeVisible();
  await expect(facts.getByText('19', { exact: true })).toBeVisible();
  expect(requests).toHaveLength(1);
  await facts.getByRole('button', { name: 'Refresh data' }).click();
  await expect(facts.getByRole('button', { name: 'Refresh data' })).toBeEnabled();
  expect(reads).toBe(2);
  expect(requests).toHaveLength(1);
  await facts.getByRole('button', { name: 'Back to investigation' }).click();
  const historical = page.getByRole('group', { name: 'Container status', exact: true });
  await expect(historical.locator('footer time')).toHaveAttribute('datetime', snapshot.observed_at);
  await expect(historical.getByText('9', { exact: true })).toBeVisible();
  await chooseContainer(page, snapshot.name);
  await expect.poll(() => reads).toBe(3);
  await facts.getByRole('button', { name: 'Diagnose', exact: true }).click();
  await expect.poll(() => requests.length).toBe(2);
  expect(requests[1]).toEqual({
    host: snapshot.host,
    query: `Investigate ${snapshot.name} (${snapshot.id}). What happened, and what evidence supports it?`,
  });
  await expect(page.getByRole('heading', { name: requests[1]!.query, exact: true })).toBeVisible();
  await page.locator('.session-turns summary').click();
  await page.getByRole('button', { name: /Original investigation/ }).click();
  await expect(historical.locator('footer time')).toHaveAttribute('datetime', snapshot.observed_at);
});

test('keeps large untrusted observations bounded and retains successful data after a failed refresh', async ({
  page,
}, info) => {
  const snapshot = demoContainer(2, 'test-host', '2026-10-27T12:00:00Z');
  snapshot.name = `checkout-${'long-service-name-'.repeat(10)}`;
  snapshot.environment = [['VERY_LONG_KEY_' + 'X'.repeat(60), '<script>alert(1)</script>' + 'x'.repeat(800)]];
  let logReads = 0;
  const calls: string[] = [];
  await page.route('**/api/v1/**', (route) => {
    const request = route.request();
    expect(request.method()).toBe('GET');
    const path = new URL(request.url()).pathname;
    calls.push(path);
    if (path.endsWith('/system/status'))
      return route.fulfill({ json: demoSystemStatus(new URL(request.url()).searchParams.get('host')) });
    if (path.endsWith('/hosts')) return route.fulfill({ json: [{ id: snapshot.host, name: 'Test host' }] });
    if (path.endsWith('/containers')) return route.fulfill({ json: [snapshot] });
    if (path.endsWith('/stats'))
      return route.fulfill({ json: { cpu_percent: 0, memory_usage_bytes: 0, memory_limit_bytes: null } });
    if (path.endsWith('/logs')) {
      expect(new URL(request.url()).searchParams.get('lines')).toBe('200');
      if (++logReads === 2)
        return route.fulfill({ status: 503, json: { code: 'runtime_unavailable', message: 'Logs unavailable' } });
      return route.fulfill({
        json: {
          entries: Array.from({ length: 200 }, (_, i) => ({
            timestamp: new Date(Date.parse('2026-10-27T23:58:20Z') + i * 1000).toISOString(),
            message:
              i === 199
                ? 'database system is shut down'
                : `<img src=x onerror=alert(1)> ${i} ${'original log '.repeat(50)}`,
          })),
          truncated: true,
        },
      });
    }
    return route.fulfill({ json: snapshot });
  });
  await page.goto('/');
  await connectApi(page);
  await chooseContainer(page, snapshot.name);
  const facts = page.getByRole('region', { name: 'Container facts', exact: true });
  await expect(facts.getByRole('heading', { name: snapshot.name, exact: true })).toBeFocused();
  await expect(facts.getByRole('button', { name: 'Refresh data' })).toBeEnabled();
  const logs = facts.getByRole('region', { name: 'Timestamped container logs' });
  await expect(logs.locator('.log-line')).toHaveCount(200);
  await expect(facts.locator('.log-window')).toContainText('2026-10-27 23:58:20 UTC');
  await expect(facts.locator('.log-window')).toContainText('2026-10-28 00:01:39 UTC');
  await expect(facts.getByText('0.0%')).toBeVisible();
  await expect(facts.getByText('0 B', { exact: true })).toBeVisible();
  await expect(facts.getByText('Unavailable', { exact: true })).toBeVisible();
  const receivedAt = await facts
    .getByRole('region', { name: 'Container logs', exact: true })
    .locator('footer time')
    .getAttribute('datetime');
  await logs.focus();
  await page.keyboard.press('End');
  await expect(logs.getByText('database system is shut down')).toBeInViewport();
  await facts.getByRole('region', { name: 'Container logs', exact: true }).screenshot({
    path: `test-results/${info.project.name}-log-window.png`,
  });
  expect(await logs.evaluate((element) => element.scrollHeight > element.clientHeight)).toBe(true);
  expect(await logs.locator('img').count()).toBe(0);
  expect(await facts.locator('.env-list script').count()).toBe(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await facts.getByRole('button', { name: 'Refresh data' }).click();
  await expect(facts.getByRole('alert')).toHaveText('Could not read container logs.');
  await expect(logs.locator('.log-line')).toHaveCount(200);
  await expect(
    facts.getByRole('region', { name: 'Container logs', exact: true }).locator('footer time'),
  ).toHaveAttribute('datetime', receivedAt!);
  expect(logReads).toBe(2);
  await page.screenshot({ path: `test-results/${info.project.name}-container-error.png`, fullPage: true });
  await facts.getByRole('button', { name: 'Retry data' }).click();
  await expect(facts.getByRole('alert')).toHaveCount(0);
  expect(logReads).toBe(3);
  expect(calls.every((path) => !path.includes('/chat/') && !path.includes('/actions'))).toBe(true);
});

test('keeps demo reads localized and keyboard accessible without translating log text', async ({ page }, info) => {
  await page.goto('/');
  await page.getByRole('combobox', { name: 'Language' }).selectOption('ru');
  await chooseContainer(page, 'payments-api', true);
  const facts = page.getByRole('region', { name: 'Факты о контейнере', exact: true });
  await expect(facts.getByRole('heading', { name: 'payments-api' })).toBeFocused();
  await expect(facts.getByRole('button', { name: 'Обновить данные' })).toBeEnabled();
  await expect(facts.getByText('Starting application bootstrap')).toBeVisible();
  await expect(facts.getByText('Код выхода')).toBeVisible();
  await expect(facts.getByText('Недоступно', { exact: true })).toHaveCount(3);
  await expect(facts.getByRole('button', { name: /Проверить (остановку|перезапуск)/ })).toHaveCount(0);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: `test-results/${info.project.name}-ru-container.png`, fullPage: true });
  await facts.getByRole('button', { name: 'Вернуться к расследованию' }).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('heading', { name: 'Диагностика контейнера', exact: true })).toBeFocused();
  await expect(page.getByRole('button', { name: 'Проверить остановку' })).toBeVisible();
});
