import { openDemo } from './helpers/demo';
import { expect, test } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await openDemo(page);
});

test('offers a styled scope menu and keeps tentative keyboard choices reversible', async ({ page }) => {
  const scope = page.getByRole('combobox', { name: 'Investigation scope', exact: true });
  await scope.click();
  await expect(page.getByRole('listbox', { name: 'Investigation scope', exact: true })).toBeVisible();
  await expect(page.getByRole('option', { name: 'Automatic', exact: true })).toHaveAttribute('aria-selected', 'true');
  await scope.press('End');
  await scope.press('Escape');
  await expect(scope).toContainText('Automatic');
  await expect(scope).toBeFocused();
  await scope.press('ArrowDown');
  await scope.press('c');
  await scope.press('Enter');
  await expect(scope).toContainText('Compose projects');
  await expect(page.getByRole('combobox', { name: 'Group', exact: true })).toBeVisible();
  await expect(page.getByRole('listbox')).toHaveCount(0);
  await scope.press('Home');
  await scope.press('s');
  await scope.press('Enter');
  await expect(scope).toContainText('Swarm stacks');
  await scope.press('c');
  await scope.press('Enter');
  await expect(scope).toContainText('Compose projects');
});

test('shows optional scope help without permanent text and dismisses it with Escape', async ({ page }) => {
  const help = page.getByRole('button', { name: 'About investigation scope' });
  await expect(page.getByRole('tooltip')).toHaveCount(0);
  await help.focus();
  await expect(page.getByRole('tooltip')).toContainText('Automatic');
  await help.press('Escape');
  await expect(page.getByRole('tooltip')).toHaveCount(0);
  await help.click();
  await expect(page.getByRole('tooltip')).toBeVisible();
  await page.getByRole('heading', { name: 'Container investigation', exact: true }).click();
  await expect(page.getByRole('tooltip')).toHaveCount(0);
});

test('keeps scope help readable while the pointer moves from its trigger into the hint', async ({ page }, info) => {
  test.skip(info.project.name === 'mobile', 'Touch help is covered by the focus and tap scenario.');
  const help = page.getByRole('button', { name: 'About investigation scope' });
  await help.hover();
  const tooltip = page.getByRole('tooltip');
  await expect(tooltip).toBeVisible();
  const box = (await tooltip.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 12 });
  await expect(tooltip).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(tooltip).toHaveCount(0);
});

test('dismisses a provider menu before its dialog and restores focus', async ({ page }) => {
  await page.getByRole('button', { name: /^Choose model/ }).click();
  const dialog = page.getByRole('dialog', { name: 'Choose model', exact: true });
  const provider = dialog.getByRole('combobox', { name: 'Provider', exact: true });
  await provider.click();
  await expect(page.getByRole('listbox', { name: 'Provider', exact: true })).toBeVisible();
  await provider.press('Escape');
  await expect(dialog).toBeVisible();
  await expect(provider).toBeFocused();
  await expect(page.getByRole('listbox')).toHaveCount(0);
  await provider.press('Escape');
  await expect(dialog).toHaveCount(0);
});

test('tabbing past the current Demo scenario preserves the follow-up draft', async ({ page }) => {
  const draft = page.getByRole('textbox');
  await draft.fill('Keep this follow-up draft');
  const scenario = page.getByRole('combobox', { name: 'Demo scenario', exact: true });
  await scenario.click();
  await scenario.press('Tab');
  await expect(draft).toHaveValue('Keep this follow-up draft');
  await expect(page.getByRole('listbox')).toHaveCount(0);
});
