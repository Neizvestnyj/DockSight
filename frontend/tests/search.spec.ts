import { expect, test, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { randomUUID } from 'node:crypto';
import { openDemo } from './helpers/demo';
import { savedApi } from './helpers/saved-api';
import type { SavedTurn } from '../src/shared/contracts/investigation-contracts';

/** Open the shared navigation dialog at compact widths. */
async function openSidebar(page: Page) {
  const trigger = page.getByRole('button', { name: 'Open host and containers' });
  if (await trigger.isVisible()) await trigger.click();
}

test('finds a question outside both initial pages and opens its exact saved answer', async ({ page }, info) => {
  const server = await savedApi(page);
  const chat = server.chats[11]!;
  const latest = chat.turns.items[0] as SavedTurn;
  const old: SavedTurn = { ...latest, id: randomUUID(), query: 'Why did checkout report connection refused?' };
  await page.route('**/api/v1/investigations/search', (route) => {
    expect(route.request().method()).toBe('POST');
    expect(route.request().postDataJSON()).toEqual({ q: 'connection refused' });
    return route.fulfill({
      json: {
        items: [
          {
            id: chat.id,
            host: chat.host,
            title: chat.title,
            updated_at: chat.updated_at,
            match: { turn_id: old.id, excerpt: old.query, start: 24, end: 42 },
          },
        ],
        next_cursor: null,
      },
    });
  });
  await page.route(`**/api/v1/turns/${old.id}`, (route) => route.fulfill({ json: old }));
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Archived question 1' })).toBeVisible();
  await openSidebar(page);
  await page.getByRole('button', { name: 'Search chats', exact: true }).click();
  const field = page.getByRole('searchbox', { name: 'Search chats' });
  await expect(field).toBeFocused();
  await field.fill('connection refused');
  const result = page.getByRole('button', { name: /Archived question 12.*connection refused/ });
  await expect(result.locator('mark')).toHaveText('connection refused');
  await page.screenshot({ path: `test-results/${info.project.name}-chat-search.png` });
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await result.click();
  await expect(page.getByRole('heading', { name: old.query })).toBeFocused();
  expect(server.submissions).toEqual([]);
  await page.getByRole('button', { name: 'Back to latest answer' }).click();
  await expect(page.getByRole('heading', { name: latest.query })).toBeVisible();
});

test('searches the active Demo inventory and opens the selected container', async ({ page }, info) => {
  await openDemo(page);
  await openSidebar(page);
  const search = page.getByRole('button', { name: 'Search containers', exact: true });
  await search.click();
  const field = page.getByRole('searchbox', { name: 'Search containers' });
  await expect(field).toBeFocused();
  await field.fill('missing-worker');
  await expect(page.getByText('No matching containers.')).toBeVisible();
  await page.getByRole('button', { name: 'Clear search' }).click();
  await expect(field).toBeFocused();
  await expect(field).toHaveValue('');
  await field.fill('reports:1.6');
  const result = page.getByRole('button', { name: /report-worker.*exited/ });
  await expect(result).toBeVisible();
  await page.getByText('Configured host', { exact: true }).filter({ visible: true }).click();
  await expect(field).toHaveValue('reports:1.6');
  await expect(result).toBeVisible();
  await page.screenshot({ path: `test-results/${info.project.name}-container-search.png` });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await result.click();
  const facts = page.getByRole('region', { name: 'Container facts', exact: true });
  await expect(facts.getByRole('heading', { name: 'report-worker', exact: true })).toBeFocused();
});

test('a title-only match opens the current chat from container facts', async ({ page }) => {
  const server = await savedApi(page);
  const chat = server.chats[0]!;
  await page.route('**/api/v1/investigations/search', (route) =>
    route.fulfill({
      json: {
        items: [{ id: chat.id, host: chat.host, title: chat.title, updated_at: chat.updated_at, match: null }],
        next_cursor: null,
      },
    }),
  );
  await page.goto('/');
  const heading = page.getByRole('heading', { name: 'Archived question 1' });
  await expect(heading).toBeVisible();
  await openSidebar(page);
  await page.getByTitle('payments-api', { exact: true }).filter({ visible: true }).click();
  await expect(page.getByRole('region', { name: 'Container facts', exact: true })).toBeVisible();
  await openSidebar(page);
  await page.getByRole('button', { name: 'Search chats', exact: true }).click();
  await page.getByRole('searchbox', { name: 'Search chats' }).fill(chat.title);
  await page.getByRole('button', { name: /^Archived question 1 local/ }).click();
  await expect(heading).toBeVisible();
  expect(server.submissions).toEqual([]);
});

test('switches search sections and dismisses search on an outside click', async ({ page }) => {
  await savedApi(page);
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Archived question 1' })).toBeVisible();
  await openSidebar(page);

  const chats = page.getByRole('button', { name: 'Search chats', exact: true });
  const containers = page.getByRole('button', { name: 'Search containers', exact: true });
  await chats.click();
  await expect(page.getByRole('searchbox', { name: 'Search chats' })).toBeFocused();
  await containers.click();
  await expect(chats).toHaveAttribute('aria-expanded', 'false');
  await expect(page.getByRole('searchbox', { name: 'Search containers' })).toBeFocused();
  await containers.click();
  await expect(containers).toHaveAttribute('aria-expanded', 'false');
  await containers.click();

  await page.getByText('Configured host', { exact: true }).filter({ visible: true }).click();
  await expect(page.getByRole('searchbox')).toHaveCount(0);
  await expect(containers).toHaveAttribute('aria-expanded', 'false');
});
