import { chooseOption } from './helpers/select';
import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { DemoClient, demoAnswer, demoContainer, demoSystemStatus } from '../src/demo';
import { demoGroupAnswer } from '../src/demoGroup';
import type { TurnInput } from '../src/contracts';

for (const groupName of ['vintoria-infra', `vintoria-infra-${'x'.repeat(113)}`]) {
  test(`selects an observed group and retains draft, locale and history (${groupName.length} characters)`, async ({
    page,
  }, info) => {
    const inputs: TurnInput[] = [];
    const rows = Array.from({ length: 6 }, (_, index) => demoContainer(index, 'local', '2026-10-29T10:00:00Z'));
    const groups = await new DemoClient().stacks('demo-eu', 'compose', new AbortController().signal);
    const group = { ...groups[0]!, name: groupName };
    const answer = demoGroupAnswer(demoAnswer('dependency', 'local'), rows, group);
    answer.evidence.find((row) => row.kind === 'stack')!.data = { stacks: [group] };
    let finishSelection = () => {};
    const selectionGate = new Promise<void>((resolve) => {
      finishSelection = resolve;
    });
    await page.route('**/api/v1/**', async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      expect(request.headers()['authorization']).toBe('Bearer clarification-test-token');
      if (url.pathname.endsWith('/hosts')) return route.fulfill({ json: [{ id: 'local', name: 'Test host' }] });
      if (url.pathname.endsWith('/system/status')) return route.fulfill({ json: demoSystemStatus('local') });
      if (url.pathname.endsWith('/containers')) return route.fulfill({ json: rows });
      expect(url.pathname).toBe('/api/v1/chat/turns');
      inputs.push(request.postDataJSON() as TurnInput);
      if (inputs.length === 2) await selectionGate;
      const base = { schema_version: 1, request_id: `r-${inputs.length}`, turn_id: `t-${inputs.length}` };
      const events = [
        { ...base, type: 'turn.started', session_id: '62f9fcc6-583e-4b3d-9678-10ffea8ae671' },
        inputs.length === 1
          ? {
              ...base,
              type: 'clarification.required',
              selection: {
                candidates: [
                  { kind: 'compose', name: groupName },
                  groupName.length < 100
                    ? { kind: 'compose', name: 'docksight-demo' }
                    : { kind: 'swarm', name: groupName },
                ],
              },
            }
          : { ...base, type: 'answer.ready', answer },
        { ...base, type: 'turn.completed' },
      ];
      return route.fulfill({
        contentType: 'text/event-stream',
        body: events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join(''),
      });
    });
    await page.goto('/');
    if ((page.viewportSize()?.width ?? 1440) <= 560) {
      await page.getByRole('button', { name: 'Open host and containers' }).click();
      await page.getByRole('button', { name: 'Connect your API' }).click();
    } else await page.getByRole('button', { name: 'Connect API', exact: true }).click();
    await page.getByLabel('Bearer token').fill('clarification-test-token');
    await page.getByRole('button', { name: 'Connect', exact: true }).click();
    await expect(page.locator('.composer-foot')).toContainText('local');
    const question = groupName.length < 100 ? 'What happened?' : 'Что не так с винтория инфра?';
    await page.getByRole('textbox').fill(question);
    await page.getByRole('button', { name: 'Investigate', exact: true }).click();
    const selection = page.getByRole('region', { name: 'Group clarification' });
    await expect(selection).toContainText('local');
    await expect(selection.getByRole('button')).toHaveCount(2);
    await expect(page.locator('.widget-container_status')).toHaveCount(0);
    await expect(page.getByRole('alert')).toHaveCount(0);
    await page.getByRole('textbox').fill('Keep this follow-up draft');
    await chooseOption(page.getByRole('combobox', { name: 'Language' }), 'ru');
    const localized = page.getByRole('region', { name: 'Уточнение группы' });
    await expect(localized).toBeVisible();
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
    await localized.scrollIntoViewIfNeeded();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: `test-results/${info.project.name}-group-clarification-${groupName.length}.png` });
    const choice = localized.getByRole('button', { name: `Docker Compose ${groupName}`, exact: true });
    await choice.focus();
    await page.keyboard.press('Enter');
    try {
      await expect(page.locator('.session-turns')).toHaveCount(0);
      await expect(localized).toHaveCount(0);
      await expect(page.locator('.collecting')).toBeVisible();
      await expect(page.locator('.query-scope')).toContainText(groupName);
      await expect(page.getByRole('textbox')).toHaveValue('Keep this follow-up draft');
      await page.locator('.diagnostic-trace > summary').click();
      await page.screenshot({ path: `test-results/${info.project.name}-group-continuation-${groupName.length}.png` });
    } finally {
      finishSelection();
    }
    await expect(page.locator('.widget-container_status')).toHaveCount(1);
    await expect(page.locator('.diagnostic-trace')).toHaveJSProperty('open', true);
    await expect(page.locator('.session-turns')).toHaveCount(0);
    expect(inputs).toHaveLength(2);
    expect(inputs[1]?.query).toBe(question);
    expect(inputs[1]?.group).toEqual({ kind: 'compose', name: groupName });
    await expect(page.getByRole('textbox')).toHaveValue('Keep this follow-up draft');
    await page.getByRole('button', { name: 'Исследовать', exact: true }).click();
    await expect(page.locator('.session-turns')).toBeVisible();
    await page.locator('.session-turns summary').click();
    await expect(page.locator('.history-row')).toHaveCount(2);
    await page.locator('.history-row').first().click();
    await expect(page.locator('.query-line h2')).toHaveText(question);
    await expect(page.locator('.query-scope')).toContainText(groupName);
    await expect(page.locator('.widget-container_status')).toHaveCount(1);
    await expect(localized).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
