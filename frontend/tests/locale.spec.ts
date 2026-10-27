import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { demoAnswer, demoContainer } from '../src/demo';

test.use({ locale: 'ru-RU' });

test('explains demo controls, localizes every built-in scenario, and keeps empty logs empty', async ({
  page,
}, info) => {
  await page.goto('/');
  await expect(page.locator('.breadcrumb')).toContainText('Демо-хост / EU');
  await expect(page.locator('.demo-bar')).toContainText('Пример данных вымышленного хоста');
  const examples = [
    ['crash_loop', 'Почему payments-api постоянно перезапускается?', 'цикл перезапусков'],
    ['dependency', 'Почему checkout-api не запускается?', 'база данных отказала в подключении'],
    ['truncated_logs', 'Что произошло с migration-runner?', 'Логи обрезаны'],
    [
      'unconfirmed_sigkill',
      'Был ли event-consumer завершён из-за нехватки памяти?',
      'Причина завершения остаётся неизвестной',
    ],
    ['running', 'Что известно о состоянии redis по этому наблюдению?', 'единичный замер'],
    ['oom', 'Почему report-worker завершился с кодом 137?', 'нехватки памяти (OOM)'],
  ];
  for (const [scenario, query, summary] of examples) {
    await page.getByLabel('Демо-сценарий').selectOption(scenario!);
    await expect(page.getByRole('heading', { name: query, exact: true })).toBeVisible();
    await expect(page.getByRole('region', { name: 'Объяснение модели' })).toContainText(summary!);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
  await page.getByText('Проверить ошибки', { exact: true }).click();
  await expect(page.getByRole('checkbox', { name: '200 строк логов' })).toHaveCount(0);
  await page.getByLabel('Имитация подключения', { exact: true }).selectOption('stream');
  await expect(page.getByText('Отправьте вопрос, чтобы увидеть ошибку после сбора данных.')).toBeVisible();
  await page.getByLabel('После подтверждения действия', { exact: true }).selectOption('indeterminate');
  await expect(page.getByRole('region', { name: 'Логи контейнера', exact: true })).toContainText('Получено 0 строк');
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.getByRole('heading', { name: 'Диагностика контейнера' }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: `test-results/${info.project.name}-demo-clarity.png`, fullPage: true });
  await page.getByLabel('Имитация подключения', { exact: true }).selectOption('none');
  const typedQuery = 'Why did report-worker exit with code 137?';
  await page.getByRole('textbox', { name: 'Продолжить расследование' }).fill(typedQuery);
  await page.getByRole('button', { name: 'Исследовать', exact: true }).click();
  await expect(page.getByRole('heading', { name: typedQuery, exact: true })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Объяснение модели' })).toContainText('нехватки памяти (OOM)');
  await page.getByTitle('Рабочее пространство: выбрать хост').click();
  await expect(page.getByRole('dialog', { name: 'Выбрать хост' })).toContainText('Текущий хост');
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.screenshot({ path: `test-results/${info.project.name}-russian-host-picker.png` });
  await page.keyboard.press('Escape');
  if ((page.viewportSize()?.width ?? 1440) <= 1100)
    await page.getByRole('button', { name: 'Открыть хосты и контейнеры' }).click();
  await page.getByRole('button', { name: 'Обновить список контейнеров' }).click();
  await expect(page.locator('.inventory-feedback:visible')).toContainText('Список контейнеров обновлён');
  await page.screenshot({ path: `test-results/${info.project.name}-russian-refresh.png` });
});

test('localizes interrupted streams while preserving the same message when authored by the API', async ({ page }) => {
  const sourceMessage = 'Connection ended before the diagnostic turn completed. Retry manually.';
  let turns = 0;
  await page.route('**/api/v1/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/hosts')) return route.fulfill({ json: [{ id: 'local', name: 'Local' }] });
    if (path.endsWith('/containers')) return route.fulfill({ json: [] });
    turns++;
    const body =
      turns === 1
        ? ': connection closed\n\n'
        : `data: ${JSON.stringify({ type: 'turn.failed', schema_version: 1, request_id: 'r', turn_id: 't', code: 'upstream_error', message: sourceMessage })}\n\n`;
    return route.fulfill({ contentType: 'text/event-stream', body });
  });
  await page.goto('/');
  if ((page.viewportSize()?.width ?? 1440) <= 560) {
    await page.getByRole('button', { name: 'Открыть хосты и контейнеры' }).click();
    await page.getByRole('button', { name: 'Подключить свой API' }).click();
  } else await page.getByRole('button', { name: 'Подключить API', exact: true }).click();
  await page.getByLabel('Bearer-токен').fill('browser-test-token');
  await page.getByRole('button', { name: 'Подключить', exact: true }).click();
  await expect(page.locator('.composer-foot')).toContainText('local');
  await page.getByRole('textbox', { name: 'Спросить DockSight' }).fill('Проверить подключение');
  await page.getByRole('button', { name: 'Исследовать', exact: true }).click();
  await expect(page.getByRole('alert')).toHaveText(
    'Соединение прервалось до завершения диагностики. Повторите запрос вручную.',
  );
  await page.getByRole('button', { name: 'Повторить диагностику' }).click();
  await expect(page.getByRole('alert')).toHaveText(sourceMessage);
});

test('detects Russian and preserves evidence, action IDs and draft while switching', async ({ page }, info) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Диагностика контейнера' })).toBeVisible();
  await expect(page.locator('html')).toHaveAttribute('lang', 'ru');
  const summary = await page.getByRole('region', { name: 'Объяснение модели' }).locator('p').first().innerText();
  const logs = await page.getByRole('region', { name: 'Логи контейнера с временными метками' }).innerText();
  await page
    .getByRole('textbox', { name: 'Продолжить расследование' })
    .fill('Проверить зависимость без изменения логов');
  await page.getByRole('button', { name: 'Проверить остановку' }).click();
  const actionId = await page.getByRole('dialog').locator('.confirmation-facts code').last().innerText();
  await page.keyboard.press('Escape');
  await page.getByRole('combobox', { name: 'Язык' }).selectOption('en');
  await expect(page.getByRole('heading', { name: 'Container investigation' })).toBeVisible();
  await expect(page.getByRole('textbox', { name: 'Continue the investigation' })).toHaveValue(
    'Проверить зависимость без изменения логов',
  );
  expect(await page.getByRole('region', { name: 'Timestamped container logs' }).innerText()).toBe(logs);
  expect(await page.getByRole('region', { name: 'Model explanation' }).locator('p').first().innerText()).not.toBe(
    summary,
  );
  await expect(page.getByRole('region', { name: 'Model explanation' })).toContainText(
    'payments-api is caught in a restart loop.',
  );
  await page.getByRole('button', { name: 'Review stop' }).click();
  expect(await page.getByRole('dialog').locator('.confirmation-facts code').last().innerText()).toBe(actionId);
  await page.keyboard.press('Escape');
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Container investigation' })).toBeVisible();
  await expect(page.getByRole('combobox', { name: 'Language' })).toHaveValue('en');
  await page.getByRole('combobox', { name: 'Language' }).selectOption('system');
  await expect(page.getByRole('heading', { name: 'Диагностика контейнера' })).toBeVisible();
  await page.getByRole('button', { name: 'Открыть логи как доказательство' }).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByLabel('Наблюдение-источник')).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.evaluate(() => document.fonts.ready);
  const fonts = await page.evaluate(() =>
    Array.from(document.fonts)
      .filter((face) => face.family.includes('IBM Plex Sans'))
      .map((face) => ({ status: face.status, range: face.unicodeRange })),
  );
  expect(
    fonts.some((face) => face.status === 'loaded' && /400/i.test(face.range)),
    JSON.stringify(fonts),
  ).toBe(true);
  await page.getByRole('heading', { name: 'Диагностика контейнера' }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: `test-results/${info.project.name}-russian.png`, fullPage: true });
  await page.getByRole('button', { name: 'Проверить остановку' }).click();
  await expect(page.getByRole('button', { name: 'Подтвердить остановку' })).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.screenshot({ path: `test-results/${info.project.name}-russian-action.png` });
});

test('does not translate API summaries, messages, logs, or environment values', async ({ page }) => {
  const answer = demoAnswer('crash_loop', 'local');
  for (const widget of answer.widgets) {
    if (widget.widget_type === 'log_anomalies')
      widget.logs.entries = [{ timestamp: null, message: 'Container investigation <script>untrusted</script>' }];
    if (widget.widget_type === 'env_inspector') widget.variables = { APP_ENV: 'Container status' };
  }
  await page.route('**/api/v1/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/hosts')) return route.fulfill({ json: [{ id: 'local', name: 'Production / EU' }] });
    if (path.endsWith('/containers'))
      return route.fulfill({ json: [demoContainer(0, 'local', new Date().toISOString())] });
    return route.fulfill({
      contentType: 'text/event-stream',
      body: `data: ${JSON.stringify({ type: 'answer.ready', schema_version: 1, request_id: 'r', turn_id: 't', answer })}\n\ndata: ${JSON.stringify({ type: 'turn.completed', schema_version: 1, request_id: 'r', turn_id: 't' })}\n\n`,
    });
  });
  await page.goto('/');
  if ((page.viewportSize()?.width ?? 1440) <= 560) {
    await page.getByRole('button', { name: 'Открыть хосты и контейнеры' }).click();
    await page.getByRole('button', { name: 'Подключить свой API' }).click();
  } else await page.getByRole('button', { name: 'Подключить API', exact: true }).click();
  await expect(page.getByRole('dialog', { name: 'Подключение к DockSight' })).toBeVisible();
  await page.getByLabel('Bearer-токен').fill('browser-test-token');
  await page.getByRole('button', { name: 'Подключить', exact: true }).click();
  await expect(page.locator('.composer-foot')).toContainText('local');
  await page.getByRole('textbox', { name: 'Спросить DockSight' }).fill('Что произошло?');
  await page.getByRole('button', { name: 'Исследовать', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Объяснение модели' })).toContainText(answer.summary);
  await expect(page.getByRole('region', { name: 'Логи контейнера с временными метками' })).toHaveText(
    'Нет времениContainer investigation <script>untrusted</script>',
  );
  await expect(page.locator('.env-list dd')).toHaveText('Container status');
  expect(await page.locator('.logs script').count()).toBe(0);
});
