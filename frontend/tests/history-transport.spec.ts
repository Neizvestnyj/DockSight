import { expect, test, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { savedApi } from './helpers/saved-api';
import { chooseOption } from './helpers/select';
import { writeFile } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import type { SavedTurn } from '../src/shared/contracts/investigation-contracts';

/** Open the existing navigation sheet when the current breakpoint folds the sidebar. */
async function navigation(page: Page) {
  if ((page.viewportSize()?.width ?? 1440) <= 1100)
    await page.getByRole('button', { name: 'Open host and containers' }).click();
}

test('keeps workspace storage details in help and sign-out visible as a button', async ({ page }, info) => {
  const api = await savedApi(page);
  await page.goto('/');
  const logout = page.getByRole('button', { name: 'Sign out', exact: true });
  await expect(logout).toBeEnabled();
  await logout.screenshot({ path: info.outputPath('sign-out.png') });
  await navigation(page);
  const storage = page.getByText('Saved chats stay on your backend.', { exact: false });
  await expect(storage).toHaveCount(0);
  await page.getByRole('button', { name: 'About this workspace' }).click();
  const help = page.getByRole('dialog', { name: 'About this workspace' });
  await expect(help).toContainText('Saved chats stay on your backend.');
  await expect(help).toContainText('Only acknowledged drafts are restored.');
  await help.screenshot({ path: info.outputPath('workspace-help.png') });
  await page.keyboard.press('Escape');
  await expect(logout).toHaveCSS('border-top-width', '1px');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await logout.click();
  await expect(page.getByRole('heading', { name: 'Sign in to DockSight' })).toBeVisible();
  expect(api.chats).toHaveLength(12);
});

test('saves pending drafts before same-row, other-chat and new-chat navigation', async ({ page }) => {
  const api = await savedApi(page);
  await page.clock.install();
  await page.goto('/');
  await expect(page.getByRole('textbox')).toHaveValue('Acknowledged draft');
  await page.clock.pauseAt(new Date(Date.now() + 1000));
  const first = api.chats[0]!;
  await page.getByRole('textbox').fill('Immediate navigation draft');
  await navigation(page);
  await page
    .getByRole('button', { name: /Archived question 1 local/, exact: false })
    .first()
    .click();
  await expect(page.getByRole('textbox')).toHaveValue('Immediate navigation draft');
  await expect.poll(() => first.workspace.draft).toBe('Immediate navigation draft');
  await page.getByRole('textbox').fill('Second immediate draft');
  await navigation(page);
  await page.getByRole('button', { name: /Archived question 2 local/ }).click();
  await expect(page.locator('.query-line h2')).toHaveText('Archived question 2');
  expect(first.workspace.draft).toBe('Second immediate draft');
  const second = api.chats[1]!;
  await page.getByRole('textbox').fill('Before new investigation');
  const initialCount = api.chats.length;
  const plus = page.locator('.workspace-nav:visible').getByRole('button', { name: 'New investigation', exact: true });
  const input = page.getByRole('textbox');
  for (const press of [1, 2, 3]) {
    await navigation(page);
    await plus.click();
    await expect(input).toHaveValue('');
    await expect(page.getByRole('button', { name: 'Why diagnosis is unavailable' })).toHaveCount(0);
    expect(api.chats).toHaveLength(initialCount);
    expect(
      api.reads.filter((request) => request === 'POST /investigations'),
      `press ${press}`,
    ).toEqual([]);
  }
  expect(second.workspace.draft).toBe('Before new investigation');
  await input.fill('An unsent question about Redis');
  await navigation(page);
  await plus.click();
  await expect(input).toHaveValue('');
  await expect.poll(() => api.chats[0]?.workspace.draft).toBe('An unsent question about Redis');
  expect(api.chats).toHaveLength(initialCount + 1);
  await navigation(page);
  await page.getByRole('button', { name: /^Untitled chat local/ }).click();
  await expect(input).toHaveValue('An unsent question about Redis');
  expect(api.submissions).toEqual([]);
});

test('opens the current and another saved chat directly from container facts', async ({ page }) => {
  const api = await savedApi(page);
  const current = api.chats[0]!;
  const other = api.chats[1]!;
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Archived question 1' })).toBeVisible();
  const pageLoads: string[] = [];
  page.on('request', (request) => {
    if (request.isNavigationRequest()) pageLoads.push(request.url());
  });
  const facts = page.getByRole('region', { name: 'Container facts', exact: true });

  await navigation(page);
  await page.getByTitle('payments-api', { exact: true }).filter({ visible: true }).click();
  await expect(facts).toBeVisible();
  await expect.poll(() => current.workspace.view).toBe('containers');
  await navigation(page);
  await page.getByRole('button', { name: /^Archived question 1 local/ }).click();
  await expect(page.getByRole('heading', { name: 'Archived question 1' })).toBeVisible();
  await expect(page.getByRole('textbox')).toHaveValue('Acknowledged draft');
  await expect(facts).toBeHidden();
  await expect.poll(() => current.workspace.view).toBe('diagnostics');

  await navigation(page);
  await page.getByTitle('payments-api', { exact: true }).filter({ visible: true }).click();
  await expect(facts).toBeVisible();
  other.workspace = {
    ...other.workspace,
    view: 'containers',
    selected_container: current.workspace.selected_container,
  };
  await navigation(page);
  await page.getByRole('button', { name: /^Archived question 2 local/ }).click();
  await expect(page.getByRole('heading', { name: 'Archived question 2' })).toBeVisible();
  await expect(facts).toBeHidden();
  await expect.poll(() => other.workspace.view).toBe('diagnostics');
  expect(pageLoads).toEqual([]);
  expect(api.submissions).toEqual([]);
  expect(api.cancellations).toEqual([]);
});

test('submits the first question while a chat on another host is working', async ({ page }) => {
  const api = await savedApi(page);
  const background = api.chats[1]!;
  background.host = 'other-host';
  background.active_turn_id = background.turns.items[0]!.id;
  await page.goto('/');
  await expect(page.getByRole('textbox')).toHaveValue('Acknowledged draft');
  await navigation(page);
  await page.locator('.workspace-nav:visible').getByRole('button', { name: 'New investigation', exact: true }).click();
  const input = page.getByRole('textbox');
  const submit = page.getByRole('button', { name: 'Investigate', exact: true });
  await expect(input).toHaveValue('');
  await expect(submit).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Why diagnosis is unavailable' })).toHaveCount(0);
  const query = 'What happened to the gateway?';
  await input.fill(query);
  await expect(submit).toBeEnabled();
  await submit.click();
  await expect(page.getByRole('heading', { name: query, exact: true })).toBeVisible();
  expect(api.submissions).toMatchObject([{ kind: 'question', query }]);
  expect(background.active_turn_id).not.toBeNull();
  expect(api.cancellations).toEqual([]);
});

test('blocks diagnosis from container facts while another chat on the same host is running', async ({ page }, info) => {
  const api = await savedApi(page);
  const background = api.chats[1]!;
  background.active_turn_id = randomUUID();
  await page.clock.install();
  await page.goto('/');
  await expect(page.getByRole('textbox')).toHaveValue('Acknowledged draft');
  await navigation(page);
  await expect(page.getByRole('status', { name: 'Diagnosis running: Archived question 2' })).toBeVisible();
  await page.locator('.workspace-nav:visible').getByRole('button', { name: 'New investigation', exact: true }).click();
  await navigation(page);
  await page.getByTitle('payments-api', { exact: true }).filter({ visible: true }).click();
  await expect(page.getByRole('region', { name: 'Container facts', exact: true })).toBeVisible();
  await chooseOption(page.getByRole('combobox', { name: 'Language' }), 'ru');

  const facts = page.getByRole('region', { name: 'Факты о контейнере', exact: true });
  const diagnose = facts.getByRole('button', { name: 'Диагностировать', exact: true });
  const tooltip = facts.getByRole('tooltip');
  const reason = 'На этом хосте выполняется диагностика в другом чате.';
  await expect(diagnose).toBeDisabled();
  await expect(diagnose).toHaveAccessibleDescription(reason);
  if (info.project.name === 'mobile') await diagnose.tap({ force: true });
  else await diagnose.focus();
  await expect(tooltip).toBeVisible();
  await expect(tooltip).toHaveText(reason);
  expect(api.submissions).toEqual([]);
  expect(api.chats).toHaveLength(12);

  background.active_turn_id = null;
  await page.clock.runFor(6000);
  await expect(diagnose).toBeEnabled();
  await expect(tooltip).toBeHidden();
  await expect(facts).toBeVisible();
});

test('localizes host-busy conflicts and refreshes activity without resubmitting', async ({ page }) => {
  const api = await savedApi(page);
  let admissions = 0;
  await page.route('**/api/v1/investigations/*/turns', (route) => {
    admissions++;
    api.chats[1]!.active_turn_id = randomUUID();
    return route.fulfill({
      status: 409,
      json: { code: 'turn_busy', message: 'A diagnostic turn is already running on this host' },
    });
  });
  await page.goto('/');
  const input = page.getByRole('textbox');
  await expect(input).toHaveValue('Acknowledged draft');
  await chooseOption(page.getByRole('combobox', { name: 'Language' }), 'ru');
  const submit = page.getByRole('button', { name: 'Исследовать', exact: true });
  await submit.click();
  await expect(page.getByText('На этом хосте уже выполняется диагностика.', { exact: true })).toBeVisible();
  await expect(submit).toBeDisabled();
  await expect(input).toHaveValue('Acknowledged draft');
  expect(admissions).toBe(1);
  expect(api.cancellations).toEqual([]);
});

test('waits for model verification before warning about a saved model', async ({ page }) => {
  const api = await savedApi(page);
  const model = { provider: 'ollama', model: 'test-model' } as const;
  api.actor.model = model;
  let complete!: () => void;
  const lookup = new Promise<void>((resolve) => {
    complete = resolve;
  });
  await page.route('**/api/v1/model-providers', async (route) => {
    await lookup;
    await route.fulfill({
      json: {
        schema_version: 1,
        default: model,
        providers: [{ id: model.provider, name: 'Ollama', configured: false, default_model: null }],
      },
    });
  });
  await page.goto('/');
  try {
    await expect(page.getByRole('textbox')).toHaveValue('Acknowledged draft');
    const warning = page.getByText(
      'A saved model or target is unavailable. Choose a current model or scope to continue.',
    );
    await expect(warning).toHaveCount(0);
    complete();
    await expect(warning).toBeVisible();
  } finally {
    complete();
  }
});

test('retains a conflicted draft when selecting another chat or new investigation', async ({ page }) => {
  const api = await savedApi(page);
  await page.goto('/');
  await expect(page.getByRole('textbox')).toHaveValue('Acknowledged draft');
  api.conflictNext = true;
  await page.getByRole('textbox').fill('Retain this conflict');
  await expect(page.getByText('This chat changed in another tab. Your draft is unsaved.')).toBeVisible();
  await navigation(page);
  await page.getByRole('button', { name: /Archived question 2 local/ }).click();
  await expect(page.locator('.query-line h2')).toHaveText('Archived question 1');
  await expect(page.getByRole('textbox')).toHaveValue('Retain this conflict');
  await navigation(page);
  await page.locator('.workspace-nav:visible').getByRole('button', { name: 'New investigation', exact: true }).click();
  await expect(page.getByRole('textbox')).toHaveValue('Retain this conflict');
  await expect(page.getByRole('button', { name: 'Use this draft' })).toBeVisible();
});

test('remembers a removed-host archive on reload while continuation stays unavailable', async ({ page }) => {
  const api = await savedApi(page);
  api.chats[1]!.host = 'removed';
  (api.chats[1]!.turns.items[0] as SavedTurn).host = 'removed';
  await page.goto('/');
  await expect(page.getByRole('textbox')).toHaveValue('Acknowledged draft');
  await navigation(page);
  await page.getByRole('button', { name: /Archived question 2 removed/ }).click();
  await expect(page.locator('.query-line h2')).toHaveText('Archived question 2');
  expect(api.actor.host).toBe('local');
  await page.reload();
  await expect(page.locator('.query-line h2')).toHaveText('Archived question 2');
  await page.getByRole('textbox').fill('Cannot continue removed host');
  await expect(page.getByRole('button', { name: 'Investigate', exact: true })).toBeDisabled();
  expect(api.submissions).toEqual([]);
});

test('keeps another preparation unavailable when its authoritative target read is blocked', async ({ page }) => {
  const api = await savedApi(page);
  await page.route('**/api/v1/actions/*', (route) =>
    route.fulfill({
      status: 409,
      json: { code: 'target_indeterminate', message: 'Inspect Docker and reconcile the previous action' },
    }),
  );
  await page.goto('/');
  await page.getByRole('button', { name: 'Review stop' }).click();
  await expect(page.getByRole('dialog')).toContainText('This saved action is unavailable.');
  await expect(page.getByRole('button', { name: 'Confirm stop' })).toHaveCount(0);
  expect(api.mutations).toBe(0);
});

test('focus refresh preserves dirty revision ownership until explicit conflict resolution', async ({ page }) => {
  const api = await savedApi(page);
  await page.clock.install();
  await page.goto('/');
  await expect(page.getByRole('textbox')).toHaveValue('Acknowledged draft');
  await page.clock.pauseAt(new Date(Date.now() + 1000));
  await page.getByRole('textbox').fill('My focus draft');
  const chat = api.chats[0]!;
  chat.workspace = { ...chat.workspace, revision: 3, draft: 'Another tab draft' };
  api.actor.last_investigation_id = api.chats[1]!.id;
  await page.evaluate(() => dispatchEvent(new Event('focus')));
  await expect(page.getByText('This chat changed in another tab. Your draft is unsaved.')).toBeVisible();
  await page.clock.runFor(300);
  expect(api.workspaceWrites).toEqual([]);
  await expect(page.getByRole('textbox')).toHaveValue('My focus draft');
  await expect(page.locator('.query-line h2')).toHaveText('Archived question 1');
  await page.getByRole('button', { name: 'Use this draft' }).click();
  await expect(page.getByText('Draft saved', { exact: true })).toBeVisible();
  expect(api.workspaceWrites).toEqual([{ id: chat.id, expected_revision: 3, draft: 'My focus draft' }]);
  expect(api.submissions).toEqual([]);
  expect(api.mutations).toBe(0);
});

test('focus refresh adopts another tab running turn and Stop cancels it without resubmission', async ({ page }) => {
  const api = await savedApi(page);
  await page.clock.install();
  await page.goto('/');
  await expect(page.getByRole('textbox')).toHaveValue('Acknowledged draft');
  await page.clock.pauseAt(new Date(Date.now() + 1000));
  const chat = api.chats[0]!;
  const running: SavedTurn = {
    ...(chat.turns.items[0] as SavedTurn),
    id: randomUUID(),
    submission_id: randomUUID(),
    query: 'Started in another tab',
    state: 'running',
    revision: 0,
    answer: null,
    finished_at: null,
  };
  chat.turns.items.push(running);
  chat.turn_count++;
  chat.active_turn_id = running.id;
  chat.workspace = { ...chat.workspace, revision: 3, draft: '' };
  await page.evaluate(() => dispatchEvent(new Event('focus')));
  await expect(page.locator('.query-line h2')).toHaveText('Started in another tab');
  await expect.poll(() => api.reads.filter((read) => read === `GET /turns/${running.id}/events`)).toHaveLength(1);
  expect(api.reads.filter((read) => read === `GET /turns/${running.id}`)).toHaveLength(1);
  await page.getByRole('button', { name: 'Stop diagnosis' }).click();
  await expect(page.getByRole('heading', { name: 'Diagnosis stopped' })).toBeVisible();
  expect(api.cancellations).toEqual([running.id]);
  expect(api.submissions).toEqual([]);
  expect(api.mutations).toBe(0);
});

test('shows progress on a background saved chat and restores its delete action after completion', async ({
  page,
}, info) => {
  const api = await savedApi(page);
  const background = api.chats[1]!;
  background.active_turn_id = randomUUID();
  await page.clock.install();
  await page.goto('/');
  const draft = page.getByRole('textbox');
  await expect(draft).toHaveValue('Acknowledged draft');
  await navigation(page);
  const history = page.getByRole('region', { name: 'Saved chats' });
  const activity = history.getByRole('status', { name: 'Diagnosis running: Archived question 2' });
  const remove = history.getByRole('button', { name: 'Delete saved chat: Archived question 2', exact: true });
  await expect(activity).toBeVisible();
  await expect(remove).toHaveCount(0);
  await expect(
    history.getByRole('button', { name: 'Delete saved chat: Archived question 1', exact: true }),
  ).toBeEnabled();
  await history.screenshot({ path: info.outputPath('saved-chat-activity.png') });
  await expect.poll(() => api.reads).toContain(`GET /investigations/${background.id}`);

  background.active_turn_id = null;
  await page.clock.runFor(6000);
  await expect(remove).toBeEnabled();
  await expect(activity).toHaveCount(0);
  if ((page.viewportSize()?.width ?? 1440) <= 1100) await page.keyboard.press('Escape');
  await expect(draft).toHaveValue('Acknowledged draft');
  expect(api.submissions).toEqual([]);
  expect(api.cancellations).toEqual([]);
});

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
