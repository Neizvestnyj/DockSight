import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test('switches simulated models without losing the investigation, draft or prepared action', async ({ page }, info) => {
  const requests: string[] = [];
  page.on('request', (request) => {
    if (request.url().includes('/api/v1/')) requests.push(request.url());
  });
  await page.goto('/');
  await page.getByRole('textbox').fill('Keep this follow-up');
  await page.getByRole('button', { name: 'Review stop' }).click();
  const action = await page.getByRole('dialog').locator('.confirmation-facts code').last().innerText();
  await page.keyboard.press('Escape');
  const trigger = page.getByRole('button', { name: /Choose model/ });
  await trigger.click();
  const picker = page.getByRole('dialog', { name: 'Choose model' });
  await expect(picker).toContainText('Demo models · no provider requests');
  await expect(picker.getByRole('option', { name: 'OpenAI · Not configured', exact: true })).toHaveJSProperty(
    'disabled',
    true,
  );
  await picker.getByRole('combobox', { name: 'Provider' }).selectOption('gemini');
  await picker.getByRole('searchbox', { name: 'Search models' }).fill('not-a-model');
  await expect(picker).toContainText('No matching models.');
  await picker.getByRole('searchbox', { name: 'Search models' }).fill('');
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: `test-results/${info.project.name}-model-picker.png` });
  await picker.getByRole('button', { name: 'gemini-demo' }).click();
  await expect(trigger).toContainText('gemini-demo');
  await expect(trigger).toBeFocused();
  await expect(page.getByRole('textbox')).toHaveValue('Keep this follow-up');
  await expect(page.getByText('Diagnostic conclusion')).toBeVisible();
  await page.getByRole('button', { name: 'Review stop' }).click();
  expect(await page.getByRole('dialog').locator('.confirmation-facts code').last().innerText()).toBe(action);
  await page.keyboard.press('Escape');
  await page.getByRole('combobox', { name: 'Language' }).selectOption('ru');
  await page.getByRole('button', { name: /Выбрать модель/ }).click();
  await expect(page.getByRole('dialog', { name: 'Выбрать модель' })).toContainText('gemini-demo');
  await page.keyboard.press('Escape');
  await expect(page.getByRole('textbox')).toHaveValue('Keep this follow-up');
  expect(requests).toEqual([]);
});

test('disables selection during a diagnostic turn and resets it after page reload', async ({ page }) => {
  await page.goto('/');
  const trigger = page.getByRole('button', { name: /Choose model/ });
  await trigger.click();
  await page.getByRole('dialog').getByRole('combobox', { name: 'Provider' }).selectOption('gemini');
  await page.getByRole('button', { name: 'gemini-demo' }).click();
  await page.getByRole('textbox').fill('Inspect payments-api');
  await page.getByRole('button', { name: 'Investigate', exact: true }).click();
  await expect(trigger).toBeDisabled();
  await expect(trigger).toBeEnabled({ timeout: 15_000 });
  await page.reload();
  await expect(trigger).toContainText('qwen3.5:9b');
});
