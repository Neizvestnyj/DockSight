import { expect, test, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { demoAnswer, demoContainer } from '../src/demo';

/** Open connection settings through the visible control at each breakpoint. */
async function connectApi(page: Page) {
  if ((page.viewportSize()?.width ?? 1440) <= 560) {
    await page.getByRole('button', { name: 'Open host and containers' }).click();
    await page.getByRole('button', { name: 'Connect your API' }).click();
  } else await page.getByRole('button', { name: 'Connect API', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(1);
  await expect(page.getByRole('dialog', { name: 'Connect to DockSight' })).toBeVisible();
  await page.getByLabel('Bearer token').fill('browser-test-token');
  await page.getByRole('button', { name: 'Connect', exact: true }).click();
  await expect(page.locator('.composer-foot')).toContainText('test-host');
}

/** Frame test data exactly as the backend's SSE encoder does. */
function sse(type: string, values: object = {}) {
  return `event: ${type}\ndata: ${JSON.stringify({ schema_version: 1, request_id: 'test-request', turn_id: 'test-turn', type, ...values })}\n\n`;
}

test.beforeEach(async ({ page }) => {
  await page.goto('/');
});

test('shows the product, all widgets, and accessible evidence navigation', async ({ page }, info) => {
  await expect(page.getByRole('heading', { name: 'Container investigation' })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Container status', exact: true })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Container logs', exact: true })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Environment', exact: true })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Stack context', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'View log evidence' }).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByLabel('Evidence observation')).toBeFocused();
  await expect(page.getByLabel('Evidence observation')).toContainText('Docker logs');
  await expect(page.locator('body')).not.toHaveJSProperty('scrollWidth', 0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.screenshot({ path: `test-results/${info.project.name}-workspace.png`, fullPage: true });
});

test('renders OOM, uncertainty, absent logs, and truncated data honestly', async ({ page }) => {
  await page.getByLabel('Demo scenario').selectOption('oom');
  await expect(page.getByRole('region', { name: 'Container status', exact: true })).toContainText('137');
  await expect(page.getByRole('region', { name: 'Container status', exact: true })).toContainText('Unavailable');
  await page.getByLabel('Demo scenario').selectOption('unconfirmed_sigkill');
  await expect(page.getByText('Cause uncertain', { exact: true })).toBeVisible();
  await expect(page.getByText(/No log entries returned/)).toBeVisible();
  await page.getByLabel('Demo scenario').selectOption('truncated_logs');
  await expect(page.getByText('Truncated · partial evidence')).toBeVisible();
  await page.getByLabel('Demo scenario').selectOption('dependency');
  await expect(page.getByRole('region', { name: 'Model explanation' })).toContainText('unavailable dependency');
  await page.getByLabel('Demo scenario').selectOption('running');
  await expect(page.getByRole('region', { name: 'Container status', exact: true })).toContainText('0.0%');
});

test('keeps retained demo controls honest across separate host sessions', async ({ page }) => {
  await page.getByLabel('Demo scenario').selectOption('oom');
  await page.getByText('Test error states', { exact: true }).click();
  await page.getByLabel('After action confirmation', { exact: true }).selectOption('indeterminate');
  for (const host of ['demo-empty', 'demo-eu']) {
    if ((page.viewportSize()?.width ?? 1440) <= 1100)
      await page.getByRole('button', { name: 'Open host and containers' }).click();
    await page.getByRole('combobox', { name: 'Configured host' }).selectOption(host);
    if (host === 'demo-empty') {
      await page.getByLabel('Demo scenario').selectOption('oom');
      await expect(page.getByText('No UI cards were returned for this answer.')).toBeVisible();
      await expect(page.getByRole('button', { name: 'Review restart' })).toHaveCount(0);
    }
  }
  await expect(page.getByRole('heading', { name: 'Start an investigation' })).toBeVisible();
  await expect(page.getByLabel('Demo scenario')).toHaveValue('oom');
  await page.getByText('Test error states', { exact: true }).click();
  await expect(page.getByLabel('After action confirmation', { exact: true })).toHaveValue('indeterminate');
  await page.getByLabel('Simulated connection', { exact: true }).selectOption('empty');
  await page.getByLabel('Demo scenario').selectOption('dependency');
  await expect(page.getByText('No UI cards were returned for this answer.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Review restart' })).toHaveCount(0);
});

test('shows failed and expired outcomes even when the operation request succeeds', async ({ page }) => {
  await page.getByText('Test error states', { exact: true }).click();
  for (const outcome of ['failed', 'expired']) {
    await page.getByLabel('Demo scenario').selectOption('crash_loop');
    await page.getByLabel('After action confirmation', { exact: true }).selectOption(outcome);
    await page.getByRole('button', { name: 'Review stop' }).click();
    await page.getByRole('button', { name: 'Confirm stop' }).click();
    await expect(page.getByRole('dialog').getByText(outcome, { exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Close', exact: true }).click();
  }
});

test('keeps large logs bounded and keyboard-scrollable', async ({ page }) => {
  const answer = demoAnswer('crash_loop', 'test-host');
  const data = {
    entries: Array.from({ length: 200 }, (_, i) => ({
      timestamp: null,
      message: `Browser test log sample ${i + 1}: application output`,
    })),
    truncated: true,
  };
  answer.widgets.find((row) => row.widget_type === 'log_anomalies')!.logs = data;
  answer.evidence.find((row) => row.kind === 'logs')!.data = data;
  await page.route('**/api/v1/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/hosts')) return route.fulfill({ json: [{ id: 'test-host', name: 'Test host' }] });
    if (path.endsWith('/containers'))
      return route.fulfill({ json: [demoContainer(0, 'test-host', new Date().toISOString())] });
    return route.fulfill({
      contentType: 'text/event-stream',
      body: sse('answer.ready', { answer }) + sse('turn.completed'),
    });
  });
  await connectApi(page);
  await page.getByRole('textbox', { name: 'Ask DockSight', exact: true }).fill('Read the log sample');
  await page.getByRole('button', { name: 'Investigate', exact: true }).click();
  const logs = page.getByRole('region', { name: 'Timestamped container logs' });
  await expect(logs.locator('.log-line')).toHaveCount(200);
  await logs.focus();
  await page.keyboard.press('End');
  expect(await logs.evaluate((element) => element.scrollHeight > element.clientHeight)).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test('can stop, manually retry, and report a terminal failure after HTTP success', async ({ page }) => {
  await page.getByLabel('Continue the investigation').fill('Inspect this container again.');
  await page.getByRole('button', { name: 'Investigate', exact: true }).click();
  await expect(page.getByRole('status', { name: 'Diagnostic progress' })).toContainText('Inspecting container state');
  await page.getByRole('button', { name: 'Stop diagnosis' }).click();
  await expect(page.getByRole('heading', { name: 'Diagnosis stopped' })).toBeVisible();
  await page.getByText('Test error states', { exact: true }).click();
  await page.getByLabel('Simulated connection', { exact: true }).selectOption('stream');
  await page.getByRole('button', { name: 'Retry diagnosis' }).click();
  await expect(page.getByRole('heading', { name: 'Diagnosis could not finish' })).toBeVisible();
  await expect(page.getByRole('alert')).toContainText('model timed out');
  await page.getByLabel('Simulated connection', { exact: true }).selectOption('offline');
  if ((page.viewportSize()?.width ?? 1440) <= 1100)
    await page.getByRole('button', { name: 'Open host and containers' }).click();
  await expect(page.getByRole('button', { name: 'Retry inventory' })).toBeVisible();
  if ((page.viewportSize()?.width ?? 1440) <= 1100) await page.getByRole('button', { name: 'Close dialog' }).click();
  await page.getByLabel('Simulated connection', { exact: true }).selectOption('empty');
  if ((page.viewportSize()?.width ?? 1440) <= 1100)
    await page.getByRole('button', { name: 'Open host and containers' }).click();
  await expect(page.getByText('No containers on this host.', { exact: true }).last()).toBeVisible();
});

test('contains focus in confirmation and explains an indeterminate operation', async ({ page }, info) => {
  await page.getByText('Test error states', { exact: true }).click();
  await page.getByLabel('After action confirmation', { exact: true }).selectOption('indeterminate');
  await page.getByRole('button', { name: 'Review stop' }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toContainText('1'.repeat(64));
  await expect(dialog).toContainText('demo-eu');
  await page.keyboard.press('Shift+Tab');
  expect(await dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true);
  await page.getByRole('button', { name: 'Confirm stop' }).click();
  await expect(dialog.getByText('indeterminate', { exact: true })).toBeVisible();
  await expect(dialog).toContainText('Docker result is not confirmed');
  await expect(page.getByRole('button', { name: 'Confirm stop' })).toHaveCount(0);
  await page.screenshot({ path: `test-results/${info.project.name}-action.png`, fullPage: true });
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
});

test('connects to authenticated POST SSE and recovers action delivery by GET only', async ({ page }) => {
  const answer = demoAnswer('crash_loop', 'test-host');
  const container = demoContainer(0, 'test-host', new Date().toISOString());
  const status = answer.widgets.find((row) => row.widget_type === 'container_status')!;
  const action = status.actions[0]!;
  let posts = 0;
  let actionReads = 0;
  await page.route('**/api/v1/**', async (route) => {
    const req = route.request();
    expect(req.headers()['authorization']).toBe('Bearer browser-test-token');
    const path = new URL(req.url()).pathname;
    if (path.endsWith('/hosts')) return route.fulfill({ json: [{ id: 'test-host', name: 'Test host' }] });
    if (path.endsWith('/containers')) return route.fulfill({ json: [container] });
    if (path.endsWith('/chat/turns')) {
      expect(req.method()).toBe('POST');
      expect(req.postDataJSON()).toEqual({ host: 'test-host', query: 'Why did this container exit?' });
      return route.fulfill({
        contentType: 'text/event-stream',
        body:
          sse('turn.started', { session_id: '4a59a145-0037-4934-92e0-f422105583b9' }) +
          sse('answer.ready', { answer }) +
          sse('turn.completed'),
      });
    }
    if (path.endsWith('/execute')) {
      posts++;
      expect(req.headers()['idempotency-key']).toBeTruthy();
      expect(req.postDataJSON()).toEqual({ confirmed: true });
      return route.abort('connectionreset');
    }
    actionReads++;
    return route.fulfill({ json: { ...action, state: 'indeterminate', message: 'Docker result unknown' } });
  });
  await connectApi(page);
  await expect(page.getByRole('heading', { name: 'Start an investigation' })).toBeVisible();
  await page.getByRole('textbox', { name: 'Ask DockSight', exact: true }).fill('Why did this container exit?');
  await page.getByRole('button', { name: 'Investigate', exact: true }).click();
  await page.getByRole('button', { name: 'Review stop' }).click();
  await page.getByRole('button', { name: 'Confirm stop' }).click();
  await expect(page.getByText('indeterminate', { exact: true })).toBeVisible();
  expect(posts).toBe(1);
  expect(actionReads).toBe(1);
  await page.getByRole('button', { name: 'Check existing action' }).click();
  await expect.poll(() => actionReads).toBe(2);
  expect(posts).toBe(1);
});

test('handles long untrusted logs, container names and environment as text', async ({ page }) => {
  const answer = demoAnswer('dependency', 'test-host');
  const container = demoContainer(2, 'test-host', new Date().toISOString());
  container.name = `checkout-${'very-long-service-name-'.repeat(12)}`;
  for (const widget of answer.widgets) {
    if (widget.widget_type === 'container_status') widget.snapshot.name = container.name;
    if (widget.widget_type === 'log_anomalies')
      widget.logs.entries = [
        { timestamp: null, message: '<img src=x onerror="window.hacked=true">' + 'x'.repeat(6000) },
      ];
    if (widget.widget_type === 'env_inspector')
      widget.variables = { VERY_LONG_KEY: '<script>alert(1)</script>' + 'x'.repeat(800) };
  }
  await page.route('**/api/v1/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/hosts')) return route.fulfill({ json: [{ id: 'test-host', name: 'Test host' }] });
    if (path.endsWith('/containers')) return route.fulfill({ json: [container] });
    return route.fulfill({
      contentType: 'text/event-stream',
      body: sse('answer.ready', { answer }) + sse('turn.completed'),
    });
  });
  await connectApi(page);
  await page.getByRole('textbox', { name: 'Ask DockSight', exact: true }).fill('Inspect the long container name.');
  await page.getByRole('button', { name: 'Investigate', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Container logs', exact: true })).toContainText('<img src=x');
  expect(await page.locator('.logs img').count()).toBe(0);
  expect(await page.locator('.env-list script').count()).toBe(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
