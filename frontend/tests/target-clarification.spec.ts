import { routeSavedApi } from './helpers/saved-server';
import { openDemo } from './helpers/demo';
import { chooseOption } from './helpers/select';
import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { demoAnswer, demoSystemStatus } from '../src/demo';
import type { StartTurn } from '../src/investigation-contracts';

for (const kind of ['container', 'compose'] as const) {
  test(`clarifies a same-name ${kind} follow-up without losing the conversation`, async ({ page }, info) => {
    const inputs: StartTurn[] = [];
    const original = demoAnswer('dependency', 'local');
    const answer = demoAnswer('oom', 'local');
    const snapshot = answer.widgets.find((row) => row.widget_type === 'container_status')!.snapshot;
    snapshot.name = 'vintoria-db';
    for (const evidence of answer.evidence) evidence.container_name = snapshot.name;
    const container = { kind: 'container', id: snapshot.id, name: snapshot.name };
    const group = { kind: 'compose', name: snapshot.name };
    const session = '62f9fcc6-583e-4b3d-9678-10ffea8ae671';
    let finish = () => {};
    const gate = new Promise<void>((resolve) => {
      finish = resolve;
    });
    await routeSavedApi(page, async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      expect(request.headers()['authorization']).toBeUndefined();
      if (url.pathname.endsWith('/hosts')) return route.fulfill({ json: [{ id: 'local', name: 'Test host' }] });
      if (url.pathname.endsWith('/system/status')) return route.fulfill({ json: demoSystemStatus('local') });
      if (url.pathname.endsWith('/containers')) return route.fulfill({ json: [snapshot] });
      if (url.pathname.endsWith(`/${snapshot.id}`)) return route.fulfill({ json: snapshot });
      expect(url.pathname.endsWith('/turns')).toBe(true);
      inputs.push(request.postDataJSON() as StartTurn);
      const index = inputs.length;
      if (index === 3) await gate;
      const base = { schema_version: 1, request_id: `r-${index}`, turn_id: `t-${index}` };
      const events = [
        { ...base, type: 'turn.started', session_id: session },
        index === 2
          ? { ...base, type: 'clarification.required', selection: { candidates: [container, group] } }
          : { ...base, type: 'answer.ready', answer: index === 1 ? original : answer },
        { ...base, type: 'turn.completed' },
      ];
      return route.fulfill({
        contentType: 'text/event-stream',
        body: events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join(''),
      });
    });
    await openDemo(page);
    if ((page.viewportSize()?.width ?? 1440) <= 560) {
      await page.getByRole('button', { name: 'Open host and containers' }).click();
      await page.getByRole('button', { name: 'Connect your API' }).click();
    } else await page.getByRole('button', { name: 'Connect API', exact: true }).click();
    await page.getByLabel('Bearer token').fill('target-test-token');
    await page.getByRole('button', { name: 'Connect', exact: true }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(page.locator('.composer-foot')).toContainText('local');
    await page.getByRole('textbox').fill('Why did vintoria-infra fail?');
    await page.getByRole('button', { name: 'Investigate', exact: true }).click();
    await expect(page.locator('.widget-container_status')).toHaveCount(1);
    await chooseOption(page.getByRole('combobox', { name: 'Language' }), 'ru');
    const question = 'А может потому-что vintoria-db не запущен?';
    await page.getByRole('textbox').fill(question);
    await page.getByRole('button', { name: 'Исследовать', exact: true }).click();
    const selection = page.getByRole('region', { name: 'Уточнение ресурса' });
    await expect(selection).toBeVisible();
    await expect(selection.getByRole('button')).toHaveCount(2);
    await expect(selection).toContainText(snapshot.id.slice(0, 12));
    await expect(page.getByRole('alert')).toHaveCount(0);
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await selection.screenshot({ path: `test-results/${info.project.name}-target-choices-${kind}.png` });
    await page.getByRole('textbox').fill('Keep this next question');
    const choice = selection.getByRole('button', {
      name: kind === 'container' ? /^Контейнер vintoria-db/ : 'Docker Compose vintoria-db',
    });
    await choice.focus();
    await page.keyboard.press('Enter');
    try {
      await expect(selection).toHaveCount(0);
      await expect(page.locator('.collecting')).toBeVisible();
      await expect(page.locator('.query-scope')).toContainText(kind === 'container' ? 'Контейнер' : 'Docker Compose');
      await page.locator('.session-turns summary').click();
      await expect(page.locator('.history-row')).toHaveCount(2);
      await expect(page.getByRole('textbox')).toHaveValue('Keep this next question');
      await page.screenshot({ path: `test-results/${info.project.name}-mixed-${kind}.png` });
    } finally {
      finish();
    }
    await expect(page.locator('.widget-container_status')).toHaveCount(1);
    await expect(page.locator('.query-line h2')).toHaveText(question);
    expect(inputs).toHaveLength(3);
    expect(inputs[2]).toMatchObject({
      kind: 'clarification',
      clarification_of: expect.any(String),
      expected_parent_revision: expect.any(Number),
      target: kind === 'container' ? container : group,
    });
    expect(inputs[2]).not.toHaveProperty('query');
    await expect(page.locator('.history-row')).toHaveCount(2);
    await page.locator('.history-row').first().click();
    await expect(page.getByRole('region', { name: 'Доказательства контейнера: checkout-api' })).toBeVisible();
    await expect(page.getByRole('textbox')).toHaveValue('Keep this next question');
    await page.getByRole('button', { name: 'Исследовать', exact: true }).click();
    await expect(page.locator('.collecting')).toHaveCount(0);
    expect(inputs[3]).toMatchObject({ kind: 'question', query: 'Keep this next question', target: null });
    await expect(page.locator('.history-row')).toHaveCount(3);
  });
}
