import { openDemo } from './helpers/demo';
import { chooseOption } from './helpers/select';
import { expect, test } from '@playwright/test';

for (const locale of ['en', 'ru'] as const) {
  test(`keeps composer hints clear of submit and stop buttons in ${locale}`, async ({ page }, info) => {
    await openDemo(page);
    await chooseOption(page.getByRole('combobox', { name: 'Language' }), locale);
    const composer = page.getByRole('form', { name: locale === 'ru' ? 'Спросить DockSight' : 'Ask DockSight' });
    const field = composer.getByRole('textbox');
    const hint = composer.locator('.query-limit');
    await composer.scrollIntoViewIfNeeded();
    await page.screenshot({ path: `test-results/${info.project.name}-${locale}-composer-empty.png` });

    await field.fill('x'.repeat(4000));
    const submit = composer.getByRole('button', { name: locale === 'ru' ? 'Исследовать' : 'Investigate', exact: true });
    if (await hint.isVisible()) {
      const text = (await hint.boundingBox())!;
      const button = (await submit.boundingBox())!;
      expect(text.x + text.width).toBeLessThanOrEqual(button.x);
    }
    await submit.click();
    const stop = composer.getByRole('button', { name: locale === 'ru' ? 'Остановить диагностику' : 'Stop diagnosis' });
    await expect(stop).toBeVisible();
    if (await hint.isVisible()) {
      const text = (await hint.boundingBox())!;
      const button = (await stop.boundingBox())!;
      expect(text.x + text.width).toBeLessThanOrEqual(button.x);
    }
    await composer.scrollIntoViewIfNeeded();
    await page.screenshot({ path: `test-results/${info.project.name}-${locale}-composer-running.png` });
    await field.fill('y'.repeat(4000));
    if (await hint.isVisible()) {
      const text = (await hint.boundingBox())!;
      const button = (await stop.boundingBox())!;
      expect(text.x + text.width).toBeLessThanOrEqual(button.x);
    }
    const form = (await composer.boundingBox())!;
    const button = (await stop.boundingBox())!;
    expect(button.x + button.width).toBeLessThanOrEqual(form.x + form.width);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await stop.click();
  });
}
