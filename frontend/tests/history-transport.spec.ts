import { expect, test, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { savedApi } from './helpers/saved-api';
import { writeFile } from 'node:fs/promises';

/** Open the existing navigation sheet when the current breakpoint folds the sidebar. */
async function navigation(page: Page) {
  if ((page.viewportSize()?.width ?? 1440) <= 1100)
    await page.getByRole('button', { name: 'Open host and containers' }).click();
}

test('bootstraps cookie history before Demo, pages older chats and restores only acknowledged drafts', async ({
  page,
}, info) => {
  const api = await savedApi(page);
  await page.goto('/');
  await expect(page.getByRole('textbox')).toHaveValue('Acknowledged draft');
  await expect(page.locator('.query-line h2')).toHaveText('Archived question 1');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.locator('.demo-bar')).toHaveCount(0);
  expect(api.submissions).toEqual([]);
  expect(api.mutations).toBe(0);
  await navigation(page);
  await expect(page.locator('.saved-chat:visible')).toHaveCount(10);
  await page.getByRole('button', { name: 'Older chats' }).click();
  await expect(page.locator('.saved-chat:visible')).toHaveCount(12);
  await page.screenshot({ path: info.outputPath('saved-chat-navigation.png') });
  await page.getByRole('button', { name: /Archived question 12 local/ }).click();
  await expect(page.locator('.query-line h2')).toHaveText('Archived question 12');
  await expect(page.getByRole('textbox')).toHaveValue('');
  await page.getByRole('textbox').fill('Saved next question');
  await expect(page.getByText('Draft saved', { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.locator('.query-line h2')).toHaveText('Archived question 12');
  await expect(page.getByRole('textbox')).toHaveValue('Saved next question');
  expect(api.submissions).toEqual([]);
  await expect(page.getByRole('dialog')).toHaveCount(0);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath('saved-chat-workspace.png'), fullPage: true });
  await writeFile(
    info.outputPath('saved-api-fixture.json'),
    JSON.stringify({ chats: api.chats, actor: api.actor, action: api.action }),
  );
});

test('keeps dirty text on a 409 and lets the operator explicitly save that draft', async ({ page }, info) => {
  const api = await savedApi(page);
  await page.goto('/');
  await expect(page.getByRole('textbox')).toHaveValue('Acknowledged draft');
  api.conflictNext = true;
  await page.getByRole('textbox').fill('My conflict draft');
  await expect(page.getByText('This chat changed in another tab. Your draft is unsaved.')).toBeVisible();
  await expect(page.getByRole('textbox')).toHaveValue('My conflict draft');
  await expect(page.getByRole('button', { name: 'Investigate', exact: true })).toBeDisabled();
  await page.screenshot({ path: info.outputPath('draft-conflict.png') });
  await page.getByRole('button', { name: 'Use this draft' }).click();
  await expect(page.getByText('Draft saved', { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('textbox')).toHaveValue('My conflict draft');
  expect(api.submissions).toEqual([]);
});

test('reads an archived action before renewed confirmation and keeps expired actions unavailable', async ({
  page,
}, info) => {
  const api = await savedApi(page);
  api.action = { ...api.action, state: 'expired', expires_at: '2026-01-01T12:00:00Z' };
  await page.goto('/');
  await expect(page.getByRole('button', { name: 'Review stop' })).toBeVisible();
  expect(api.reads.some((read) => read.includes('/actions/'))).toBe(false);
  await page.getByRole('button', { name: 'Review stop' }).click();
  await expect(page.getByRole('dialog')).toContainText('expired');
  await expect(page.getByRole('button', { name: 'Confirm stop' })).toHaveCount(0);
  expect(api.reads.filter((read) => read.startsWith('GET /actions/'))).toHaveLength(1);
  expect(api.mutations).toBe(0);
  await page.keyboard.press('Escape');
  await expect(page.getByRole('button', { name: 'stop: expired' })).toBeFocused();
  await page.reload();
  await expect(page.getByRole('textbox')).toHaveValue('Acknowledged draft');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  expect(api.mutations).toBe(0);
  await page.screenshot({ path: info.outputPath('archive-confirmation-closed.png') });
});

test('submits one explicit question and never repeats it on refresh', async ({ page }) => {
  const api = await savedApi(page);
  await page.goto('/');
  await expect(page.getByRole('textbox')).toHaveValue('Acknowledged draft');
  await page.getByRole('textbox').fill('Read fresh Docker evidence');
  await page.getByRole('button', { name: 'Investigate', exact: true }).click();
  await expect(page.locator('.query-line h2')).toHaveText('Read fresh Docker evidence');
  expect(api.submissions).toHaveLength(1);
  expect(api.submissions[0]).toMatchObject({
    kind: 'question',
    query: 'Read fresh Docker evidence',
    expected_revision: 3,
  });
  await page.reload();
  await expect(page.locator('.query-line h2')).toHaveText('Read fresh Docker evidence');
  expect(api.submissions).toHaveLength(1);
  expect(api.reads.some((read) => read.includes('/chat/turns'))).toBe(false);
  expect(
    await page.evaluate(() => ({ local: Object.keys(localStorage), session: Object.keys(sessionStorage) })),
  ).toEqual({ local: [], session: [] });
});
