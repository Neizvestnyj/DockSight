import { routeSavedApi } from './helpers/saved-server';
import { openDemo } from './helpers/demo';
import { chooseOption } from './helpers/select';
import { expect, test, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { demoContainer, demoSystemStatus } from '../src/demo';

/** Connect the UI to intercepted requests without reaching a real provider or Docker host. */
async function connectApi(page: Page) {
  if ((page.viewportSize()?.width ?? 1440) <= 560) {
    await page.getByRole('button', { name: 'Open host and containers' }).click();
    await page.getByRole('button', { name: 'Connect your API' }).click();
  } else await page.getByRole('button', { name: 'Connect API', exact: true }).click();
  await page.getByLabel('Bearer token').fill('browser-test-token');
  await page.getByRole('button', { name: 'Connect', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
}

test('checks model metadata independently and retains facts and timestamps through manual rechecks', async ({
  page,
}, info) => {
  const snapshot = demoContainer(0, 'local', '2026-10-27T12:00:00Z');
  const healthy = { ...demoSystemStatus('local'), provider: 'gemini', model: 'gemini-2.5-flash-lite' };
  const initial = {
    ...healthy,
    model_check: { ...healthy.model_check, state: 'unavailable', code: 'model_not_found' },
  };
  let calls = 0;
  let finish = () => {};
  const gate = new Promise<void>((resolve) => {
    finish = resolve;
  });
  await routeSavedApi(page, async (route) => {
    const request = route.request();
    expect(request.method()).toBe('GET');
    expect(request.headers()['authorization']).toBeUndefined();
    const url = new URL(request.url());
    if (url.pathname.endsWith('/hosts'))
      return route.fulfill({
        json: [
          { id: 'local', name: 'Production / EU' },
          { id: 'beta', name: 'Standby' },
        ],
      });
    if (url.pathname.endsWith('/system/status')) {
      calls++;
      const host = url.searchParams.get('host');
      if (calls === 1) return route.fulfill({ json: initial });
      if (calls === 2) {
        await gate;
        return route.fulfill({
          json: { ...healthy, model_check: { ...healthy.model_check, state: 'not_checked', code: 'unsupported' } },
        });
      }
      return route.fulfill({ json: demoSystemStatus(host) });
    }
    if (url.pathname.endsWith('/containers')) return route.fulfill({ json: [snapshot] });
    if (url.pathname.endsWith('/stats')) return route.fulfill({ json: snapshot.metrics });
    if (url.pathname.endsWith('/logs')) return route.fulfill({ json: { entries: [], truncated: false } });
    return route.fulfill({ json: snapshot });
  });
  await openDemo(page);
  await connectApi(page);
  await expect(
    page.getByText('The configured model is unavailable. You can still inspect Docker directly.'),
  ).toBeVisible();
  if ((page.viewportSize()?.width ?? 1440) <= 1100)
    await page.getByRole('button', { name: 'Open host and containers' }).click();
  await page.getByTitle(snapshot.name, { exact: true }).filter({ visible: true }).click();
  await expect(page.getByText('APP_ENV')).toBeVisible();
  const diagnose = page.getByRole('button', { name: 'Diagnose', exact: true });
  await expect(diagnose).toBeDisabled();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.getByRole('button', { name: /^System status/ }).click();
  const dialog = page.getByRole('dialog', { name: 'System status' });
  await expect(dialog.getByRole('region', { name: 'Docker', exact: true })).toContainText('Available');
  await expect(dialog.getByRole('region', { name: 'Model', exact: true })).toContainText('Unavailable');
  await expect(dialog).toContainText('Gemini · gemini-2.5-flash-lite');
  await expect(dialog).toContainText('Tools and structured output have not been tested.');
  const stamp = await dialog
    .getByRole('region', { name: 'Model', exact: true })
    .locator('time')
    .getAttribute('datetime');
  await dialog.getByRole('button', { name: 'Check again' }).click();
  try {
    await expect(dialog.getByRole('status')).toHaveText('Checking dependencies…');
    await expect(dialog.getByRole('region', { name: 'Model', exact: true }).locator('time')).toHaveAttribute(
      'datetime',
      stamp!,
    );
    await expect(dialog.getByRole('button', { name: 'Check again' })).toBeDisabled();
  } finally {
    finish();
  }
  await expect(dialog.getByRole('region', { name: 'Model', exact: true })).toContainText('Not checked');
  await expect(dialog.getByRole('button', { name: 'Check again' })).toBeEnabled();
  expect(calls).toBe(2);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: `test-results/${info.project.name}-system-status.png` });
  await page.keyboard.press('Escape');
  await expect(page.getByRole('button', { name: /^System status/ })).toBeFocused();
  await expect(diagnose).toBeEnabled();
  await page.getByTitle('Workspace: choose host').click();
  await page.getByRole('button', { name: /Standby/ }).click();
  await expect.poll(() => calls).toBe(3);
});

for (const failure of ['unauthorized', 'offline'] as const) {
  test(`reports ${failure} separately without generating an answer`, async ({ page }) => {
    await routeSavedApi(page, (route) =>
      failure === 'offline'
        ? route.abort('connectionreset')
        : route.fulfill({ status: 401, json: { code: 'unauthorized', message: 'Authentication required' } }),
    );
    await openDemo(page);
    await connectApi(page);
    await page.getByRole('button', { name: /^System status/ }).click();
    const dialog = page.getByRole('dialog', { name: 'System status' });
    await expect(dialog).toContainText(
      failure === 'unauthorized'
        ? 'The API rejected the bearer token.'
        : 'No connection to the API. Check the endpoint and network.',
    );
    await expect(dialog.getByRole('region', { name: 'Model', exact: true })).toContainText('Not checked');
    await expect(dialog.getByRole('button', { name: 'Change connection' })).toBeVisible();
  });
}

test('rechecks stale status, recovers diagnosis automatically, and stops after rejected authorization', async ({
  page,
}, info) => {
  const healthy = demoSystemStatus('local');
  let failure: 'none' | 'docker' | 'authorization' = 'none';
  let calls = 0;
  let releaseStaleCheck = () => {};
  const staleCheckGate = new Promise<void>((resolve) => {
    releaseStaleCheck = resolve;
  });
  await routeSavedApi(page, async (route) => {
    const url = new URL(route.request().url());
    expect(route.request().method()).toBe('GET');
    if (url.pathname.endsWith('/hosts')) return route.fulfill({ json: [{ id: 'local', name: 'Test host' }] });
    if (url.pathname.endsWith('/system/status')) {
      calls++;
      const checkFailure = failure;
      if (calls === 2) await staleCheckGate;
      if (checkFailure === 'authorization')
        return route.fulfill({ status: 401, json: { code: 'unauthorized', message: 'Denied' } });
      return route.fulfill({
        json:
          checkFailure === 'docker'
            ? { ...healthy, docker: { ...healthy.docker, state: 'unavailable', code: 'runtime_unavailable' } }
            : healthy,
      });
    }
    return route.fulfill({ json: [] });
  });
  await page.clock.install();
  await openDemo(page);
  await connectApi(page);
  await expect(page.locator('.composer-foot')).toContainText('local');
  const draft = page.getByRole('textbox');
  await draft.fill('Preserve this investigation');
  const trigger = page.getByRole('button', { name: /^System status/ });
  const dialog = page.getByRole('dialog', { name: 'System status' });
  await trigger.click();
  await expect(dialog).toContainText('Checks refresh every minute while this tab is visible.');
  expect(calls).toBe(1);
  await page.keyboard.press('Escape');
  await page.clock.runFor(30_000);
  await trigger.click();
  await expect.poll(() => calls).toBe(2);
  await expect(trigger).toHaveAttribute('aria-busy', 'true');
  await expect(dialog.getByRole('button', { name: 'Check again' })).toBeEnabled();
  releaseStaleCheck();
  await expect(trigger).toHaveAttribute('aria-busy', 'false');
  await page.keyboard.press('Escape');
  failure = 'docker';
  await page.clock.runFor(60_000);
  await expect(page.getByRole('button', { name: 'Investigate', exact: true })).toBeDisabled();
  await expect(
    page.getByText(
      'Docker is unavailable for this host. Diagnosis cannot collect evidence. Check the connection and try again.',
    ),
  ).toBeVisible();
  failure = 'none';
  await page.clock.runFor(120_000);
  await expect(page.getByRole('button', { name: 'Investigate', exact: true })).toBeEnabled();
  await expect(draft).toHaveValue('Preserve this investigation');
  failure = 'authorization';
  await page.clock.runFor(60_000);
  await trigger.click();
  await expect(dialog).toContainText('The API rejected the bearer token.');
  await expect(dialog).toContainText('Dependency results are from the previous successful check.');
  await expect(dialog).toContainText('Automatic checks stopped. Retry manually.');
  const deniedCalls = calls;
  await page.clock.runFor(300_000);
  expect(calls).toBe(deniedCalls);
  await page.screenshot({ path: `test-results/${info.project.name}-system-status-stopped.png` });
  failure = 'none';
  await dialog.getByRole('button', { name: 'Check again' }).click();
  await expect(dialog).toContainText('Checks refresh every minute while this tab is visible.');
  await page.keyboard.press('Escape');
  await expect(draft).toHaveValue('Preserve this investigation');
});

test('keeps demo status checks localized and preserves an investigation and its prepared action', async ({
  page,
}, info) => {
  const requests: string[] = [];
  page.on('request', (request) => {
    if (request.url().includes('/api/v1/')) requests.push(request.url());
  });
  await openDemo(page);
  await page.getByRole('textbox').fill('Keep this follow-up');
  await page.getByRole('button', { name: 'Review stop' }).click();
  const action = await page.getByRole('dialog').locator('.confirmation-facts code').last().innerText();
  await page.keyboard.press('Escape');
  await chooseOption(page.getByRole('combobox', { name: 'Language' }), 'ru');
  await page.getByRole('button', { name: /^Состояние системы/ }).focus();
  await page.keyboard.press('Enter');
  const dialog = page.getByRole('dialog', { name: 'Состояние системы' });
  await expect(dialog).toContainText('Статусы в демо смоделированы.');
  await expect(dialog).toContainText('Вызов инструментов и структурированный ответ не проверялись.');
  await dialog.getByRole('button', { name: 'Проверить снова' }).click();
  await expect(dialog.getByRole('button', { name: 'Проверить снова' })).toBeEnabled();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.screenshot({ path: `test-results/${info.project.name}-ru-system-status.png` });
  await page.keyboard.press('Escape');
  await expect(page.getByRole('textbox')).toHaveValue('Keep this follow-up');
  await page.getByRole('button', { name: 'Проверить остановку' }).click();
  expect(await page.getByRole('dialog').locator('.confirmation-facts code').last().innerText()).toBe(action);
  expect(requests.every((url) => url.endsWith('/auth/session'))).toBe(true);
});
