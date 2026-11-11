import { routeSavedApi } from './helpers/saved-server';
import { openDemo } from './helpers/demo';
import { chooseOption } from './helpers/select';
import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { demoContainer, demoSystemStatus } from '../src/demo';

const envelope = { schema_version: 1, request_id: 'request-trace-test', turn_id: 'turn-trace-test' };
const started = '2026-10-28T09:00:00Z';
const modelStep = {
  id: 'step-1',
  kind: 'model',
  operation: 'final_response',
  state: 'running',
  started_at: started,
  finished_at: null,
  duration_ms: null,
  input_tokens: null,
  output_tokens: null,
  code: null,
  issues: [],
  response: null,
  response_truncated: false,
};

/** Connect intercepted diagnostic events without reaching Docker or a model provider. */
async function api(page: Page, events: object[]) {
  const snapshot = demoContainer(0, 'local', started);
  const saved = await routeSavedApi(page, (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/hosts')) return route.fulfill({ json: [{ id: 'local', name: 'Development' }] });
    if (url.pathname.endsWith('/system/status')) return route.fulfill({ json: demoSystemStatus('local') });
    if (url.pathname.endsWith('/containers')) return route.fulfill({ json: [snapshot] });
    if (url.pathname.endsWith('/turns'))
      return route.fulfill({
        contentType: 'text/event-stream',
        body: events.map((event) => `data: ${JSON.stringify({ ...envelope, ...event })}\n\n`).join(''),
      });
    return route.abort();
  });
  await openDemo(page);
  if ((page.viewportSize()?.width ?? 1440) <= 560) {
    await page.getByRole('button', { name: 'Open host and containers' }).click();
    await page.getByRole('button', { name: 'Connect your API' }).click();
  } else await page.getByRole('button', { name: 'Connect API', exact: true }).click();
  await page.getByLabel('Bearer token').fill('trace-browser-token');
  await page.getByRole('button', { name: 'Connect', exact: true }).click();
  await expect(page.getByTitle('Workspace: choose host')).toContainText('Development');
  await page.getByRole('textbox').fill('Inspect worker');
  await page.getByRole('button', { name: 'Investigate', exact: true }).click();
  return saved;
}

for (const motion of ['no-preference', 'reduce'] as const) {
  test(`keeps trace and observation disclosures usable with motion preference ${motion}`, async ({ page }) => {
    await page.emulateMedia({ reducedMotion: motion });
    await openDemo(page);
    await page.evaluate(() => document.fonts.ready);
    for (const selector of ['.diagnostic-trace', '.raw-evidence']) {
      const disclosure = page.locator(selector);
      const text = await disclosure.textContent();
      const summary = disclosure.locator(':scope > summary');
      await summary.focus();
      await page.keyboard.press('Enter');
      await expect(disclosure).toHaveAttribute('open', '');
      await expect
        .poll(() => disclosure.evaluate((node) => getComputedStyle(node, '::details-content').opacity))
        .toBe('1');
      if (motion === 'reduce')
        expect(
          await disclosure.evaluate((node) => getComputedStyle(node, '::details-content').transitionDuration),
        ).toBe('0s');
      const openHeight = await disclosure.evaluate((node) => node.getBoundingClientRect().height);
      await page.keyboard.press('Enter');
      await summary.click();
      await summary.click();
      await expect(disclosure).not.toHaveAttribute('open');
      await expect
        .poll(() => disclosure.evaluate((node) => node.getBoundingClientRect().height))
        .toBeLessThan(openHeight);
      await page.keyboard.press('Tab');
      expect(await disclosure.evaluate((node) => node.contains(document.activeElement))).toBe(false);
      await summary.focus();
      await page.keyboard.press('Enter');
      await expect(disclosure).toHaveAttribute('open', '');
      await expect(disclosure).toHaveText(text!);
    }
  });
}

for (const failure of [
  {
    code: 'model_unavailable',
    english:
      'The configured model was not found or is unavailable to this API key. Check the model name and your access.',
    russian: 'Настроенная модель не найдена или недоступна вашему API-ключу. Проверьте название модели и доступ к ней.',
  },
  {
    code: 'model_not_supported',
    english: 'Model request rejected; verify model capabilities and configuration',
    russian: 'Провайдер отклонил запрос к модели. Проверьте её возможности и настройки.',
  },
  {
    code: 'unknown_provider_failure',
    english: 'Provider message retained verbatim',
    russian: 'Provider message retained verbatim',
  },
  {
    code: 'toString',
    english: 'Provider message retained verbatim',
    russian: 'Provider message retained verbatim',
  },
]) {
  test(`explains ${failure.code} in the selected locale without changing the failed trace`, async ({ page }) => {
    await api(page, [
      { type: 'turn.started', session_id: '62f9fcc6-583e-4b3d-9678-10ffea8ae671' },
      { type: 'trace.started', provider: 'gemini', model: 'gemini-2.5-flash-lite', started_at: started },
      { type: 'trace.step', step: { ...modelStep, state: 'failed', code: failure.code } },
      { type: 'turn.failed', code: failure.code, message: 'Provider message retained verbatim' },
    ]);
    await expect(page.getByRole('alert')).toHaveText(failure.english);
    await page.getByRole('textbox').fill('Keep this follow-up');
    await chooseOption(page.getByRole('combobox', { name: 'Language' }), 'ru');
    await expect(page.getByRole('alert')).toHaveText(failure.russian);
    await expect(page.getByRole('textbox')).toHaveValue('Keep this follow-up');
    const trace = page.locator('.diagnostic-trace');
    await trace.locator('summary').click();
    await expect(trace).toContainText(failure.code);
    await expect(trace).toContainText('request-trace-test');
    await expect(trace).toContainText('gemini-2.5-flash-lite');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}

test('keeps a demo trace open across completion, supports keyboard selection and localized copy', async ({
  page,
}, info) => {
  const apiRequests: string[] = [];
  page.on('request', (request) => {
    if (request.url().includes('/api/v1/')) apiRequests.push(request.url());
  });
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText: async (value: string) => {
          (window as Window & { traceCopy?: string }).traceCopy = value;
        },
      },
    });
  });
  await openDemo(page);
  await page.getByRole('textbox').fill('Inspect this container');
  await page.getByRole('button', { name: 'Investigate', exact: true }).click();
  const trace = page.locator('.diagnostic-trace');
  const summary = trace.locator('summary');
  await summary.focus();
  await page.keyboard.press('Enter');
  await expect(trace).toHaveAttribute('open', '');
  await expect(page.getByRole('button', { name: 'Stop diagnosis' })).toHaveCount(0);
  await expect(trace.getByText('Simulated trace · no model request')).toBeVisible();
  await trace.getByRole('button', { name: /Collecting evidence with the model/ }).click();
  await expect(trace.getByLabel('Sanitized model response')).toContainText('"tool_calls"');
  await expect(trace.getByLabel('Sanitized model response')).toContainText('"container_id": "payments-api"');
  await page.screenshot({ path: `test-results/${info.project.name}-exploration-json.png` });
  if ((page.viewportSize()?.width ?? 1440) <= 1100) await trace.getByRole('button', { name: 'Back to steps' }).click();
  const final = trace.getByRole('button', { name: /Generating the final response/ });
  await final.focus();
  await page.keyboard.press('Enter');
  await expect(trace.getByRole('region', { name: 'Trace step details' })).toContainText('Model proposal · sanitized');
  await expect(trace.locator('pre')).toContainText('payments-api');
  if ((page.viewportSize()?.width ?? 1440) <= 1100) {
    await expect(final).not.toBeVisible();
    await trace.getByRole('button', { name: 'Back to steps' }).click();
    await expect(final).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(trace.locator('pre')).toBeVisible();
  }
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await chooseOption(page.getByRole('combobox', { name: 'Language' }), 'ru');
  await expect(trace).toHaveAttribute('open', '');
  await expect(trace.getByRole('heading', { name: 'Формирование ответа' })).toBeVisible();
  await expect(trace.locator('.trace-step[aria-pressed=true]')).toContainText('Формирование ответа');
  await trace.getByRole('button', { name: 'Скопировать трассировку' }).click();
  await expect(trace.getByRole('status')).toHaveText('Трассировка скопирована');
  const copied = await page.evaluate(() => JSON.parse((window as Window & { traceCopy?: string }).traceCopy!));
  expect(copied.simulated).toBe(true);
  expect(copied.steps).toHaveLength(7);
  expect(JSON.stringify(copied)).not.toContain('Inspect this container');
  expect(apiRequests.every((url) => url.endsWith('/auth/session'))).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await trace.scrollIntoViewIfNeeded();
  await page.screenshot({ path: `test-results/${info.project.name}-diagnostic-trace.png` });
});

test('shows saved validation failure without retaining model output previews', async ({ page }, info) => {
  const response = JSON.stringify(
    { summary: '<img src=x onerror=alert(1)>', evidence_ids: ['unverified'], uncertain: true, widgets: [] },
    null,
    2,
  );
  await api(page, [
    { type: 'turn.started', session_id: '62f9fcc6-583e-4b3d-9678-10ffea8ae671' },
    { type: 'trace.started', provider: 'compatible', model: 'gateway-'.repeat(30), started_at: started },
    { type: 'trace.step', step: modelStep },
    {
      type: 'trace.step',
      step: {
        ...modelStep,
        state: 'succeeded',
        duration_ms: 400,
        finished_at: '2026-10-28T09:00:00.400Z',
        input_tokens: 0,
        response: response + ' '.repeat(15_000),
        response_truncated: true,
      },
    },
    {
      type: 'trace.step',
      step: {
        ...modelStep,
        id: 'step-2',
        kind: 'validation',
        operation: 'validate_diagnosis',
        state: 'failed',
        duration_ms: 1,
        finished_at: '2026-10-28T09:00:00.401Z',
        code: 'invalid_evidence',
        issues: [{ type: 'invalid_reference', loc: ['evidence_ids', 0] }],
      },
    },
    {
      type: 'turn.failed',
      code: 'invalid_diagnosis',
      message: 'Model could not produce a valid evidence-backed diagnosis',
    },
  ]);
  await expect(page.getByRole('alert')).toContainText('Model could not produce');
  const trace = page.locator('.diagnostic-trace');
  await trace.locator('summary').click();
  if ((page.viewportSize()?.width ?? 1440) <= 1100)
    await trace.getByRole('button', { name: /Validating schema and evidence/ }).click();
  await expect(trace).toContainText('invalid_reference');
  if ((page.viewportSize()?.width ?? 1440) <= 1100) await trace.getByRole('button', { name: 'Back to steps' }).click();
  await trace.getByRole('button', { name: /Generating the final response/ }).click();
  await expect(trace.locator('pre')).toHaveCount(0);
  await expect(trace).toContainText('Proposal unavailable. Invalid or oversized response bodies are withheld.');
  await expect(page.locator('img[src=x]')).toHaveCount(0);
  await expect(trace.getByText('The displayed response is incomplete.')).toHaveCount(0);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await trace.scrollIntoViewIfNeeded();
  await page.screenshot({ path: `test-results/${info.project.name}-failed-trace.png` });
});

test('retains interrupted steps after a lost stream and keeps them on the original historical turn', async ({
  page,
}) => {
  const saved = await api(page, [
    { type: 'turn.started', session_id: '62f9fcc6-583e-4b3d-9678-10ffea8ae671' },
    { type: 'trace.started', provider: 'ollama', model: 'qwen3.5:9b', started_at: started },
    { type: 'trace.step', step: modelStep },
  ]);
  await expect(page.getByText('Observation disconnected. Reconnecting to the saved turn.')).toBeVisible();
  saved.failRunning({ code: 'interrupted', message: 'Diagnostic work was interrupted' });
  await expect(page.getByRole('alert')).toContainText('Diagnostic work was interrupted');
  const trace = page.locator('.diagnostic-trace');
  await trace.locator('summary').click();
  if ((page.viewportSize()?.width ?? 1440) <= 1100)
    await trace.getByRole('button', { name: /Generating the final response/ }).click();
  await expect(trace).toContainText('Interrupted');
  await expect(trace).toContainText('Its completion is unknown.');
  await page.getByRole('textbox').fill('Keep this follow-up');
  await page.getByRole('button', { name: 'Retry diagnosis' }).click();
  await expect(page.locator('.session-turns')).toBeVisible();
  await page.locator('.session-turns summary').click();
  await page.locator('.history-row').first().click();
  await trace.locator('summary').click();
  await expect(trace).toContainText('request-trace-test');
  await expect(trace.getByRole('button', { name: /Generating the final response/ })).toHaveCount(1);
});
