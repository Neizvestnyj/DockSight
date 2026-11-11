import { randomUUID } from 'node:crypto';
import { test, expect } from './fixtures/persistent-api';
import type { SavedTurn } from '../src/investigation-contracts';
import type { Page } from '@playwright/test';

/** Open the archived card's ordinary operations before reviewing the exact server action. */
async function reviewRestart(page: Page) {
  await page.locator('.card-actions-menu summary').click();
  await page.getByRole('button', { name: 'Review restart', exact: true }).click();
}

test('real cookie login and F5 restore one saved answer without another submit', async ({ page, persistent }) => {
  let submissions = 0;
  let legacy = 0;
  page.on('request', (request) => {
    if (request.method() === 'POST' && /\/investigations\/[^/]+\/turns$/.test(request.url())) submissions++;
    if (request.url().includes('/chat/turns')) legacy++;
  });
  await persistent.login(page);
  await page.getByRole('textbox').fill('Inspect worker');
  await page.getByRole('button', { name: 'Investigate', exact: true }).click();
  await expect(page.getByText('Retained worker answer', { exact: true })).toBeVisible();
  const chat = await persistent.current();
  const saved = chat.turns.items[0]!;
  await page.reload();
  await expect(page.getByText('Retained worker answer', { exact: true })).toBeVisible();
  expect((await persistent.current()).turns.items[0]).toEqual(saved);
  expect(submissions).toBe(1);
  expect(legacy).toBe(0);
  expect((await persistent.events()).filter((row) => row.event.startsWith('model.')).map((row) => row.event)).toEqual([
    'model.exploration',
    'model.final',
  ]);
  const cookies = await page.context().cookies();
  expect(cookies).toHaveLength(1);
  expect(cookies[0]).toMatchObject({ httpOnly: true, sameSite: 'Lax' });
  expect(
    await page.evaluate(() => ({ local: Object.keys(localStorage), session: Object.keys(sessionStorage) })),
  ).toEqual({ local: [], session: [] });
});

test('F5 during blocked work observes the same accepted turn and normal model calls', async ({ page, persistent }) => {
  await persistent.block('model');
  await persistent.login(page);
  await page.getByRole('textbox').fill('Inspect worker');
  await page.getByRole('button', { name: 'Investigate', exact: true }).click();
  await persistent.marker('model.entered');
  const chat = await persistent.current();
  const id = chat.active_turn_id!;
  await page.reload();
  await expect(page.getByRole('button', { name: 'Stop diagnosis' })).toBeVisible();
  expect((await persistent.current()).active_turn_id).toBe(id);
  expect((await persistent.events()).filter((row) => row.event.startsWith('model.'))).toHaveLength(1);
  await persistent.release('model');
  await expect(page.getByText('Retained worker answer', { exact: true })).toBeVisible();
  expect((await persistent.current()).turns.items).toHaveLength(1);
  expect((await persistent.events()).filter((row) => row.event.startsWith('model.')).map((row) => row.event)).toEqual([
    'model.exploration',
    'model.final',
  ]);
});

test('lost acceptance delivery recovers through saved reads without resubmitting', async ({ page, persistent }) => {
  await persistent.block('model');
  await persistent.login(page);
  let posts = 0;
  await page.route('**/investigations/*/turns', async (route) => {
    if (route.request().method() !== 'POST') return route.continue();
    posts++;
    const response = await route.fetch();
    expect(response.status()).toBe(202);
    await route.abort('failed');
  });
  await page.getByRole('textbox').fill('Inspect worker');
  await page.getByRole('button', { name: 'Investigate', exact: true }).click();
  await persistent.marker('model.entered');
  const id = (await persistent.current()).active_turn_id;
  await page.reload();
  await expect(page.getByRole('button', { name: 'Stop diagnosis' })).toBeVisible();
  expect((await persistent.current()).active_turn_id).toBe(id);
  expect(posts).toBe(1);
  await persistent.release('model');
  await expect(page.getByText('Retained worker answer', { exact: true })).toBeVisible();
  expect(posts).toBe(1);
});

test('observer reconnection reads the accepted turn without automatic submission', async ({ page, persistent }) => {
  await persistent.login(page);
  await persistent.block('model');
  await page.clock.install();
  let observers = 0;
  let submissions = 0;
  page.on('request', (request) => {
    if (request.method() === 'POST' && /\/investigations\/[^/]+\/turns$/.test(request.url())) submissions++;
  });
  await page.route('**/turns/*/events', async (route) => {
    observers++;
    if (observers === 1) await route.abort('connectionreset');
    else await route.continue();
  });
  await page.getByRole('textbox').fill('Inspect worker');
  await page.getByRole('button', { name: 'Investigate', exact: true }).click();
  await persistent.marker('model.entered');
  const id = (await persistent.current()).active_turn_id!;
  await expect.poll(() => observers).toBe(1);
  await page.clock.runFor(1000);
  await expect.poll(() => observers).toBe(2);
  expect((await persistent.current()).active_turn_id).toBe(id);
  expect(submissions).toBe(1);
  await persistent.release('model');
  await expect(page.getByText('Retained worker answer', { exact: true })).toBeVisible();
  expect((await persistent.current()).turn_count).toBe(1);
  expect(submissions).toBe(1);
  expect((await persistent.events()).filter((row) => row.event.startsWith('model.')).map((row) => row.event)).toEqual([
    'model.exploration',
    'model.final',
  ]);
});

test('dirty focus refresh keeps local base and resolves a real SQLite revision conflict', async ({
  page,
  persistent,
}) => {
  await persistent.login(page);
  await page.getByRole('textbox').fill('Acknowledged draft');
  await expect(page.getByText('Draft saved', { exact: true })).toBeVisible();
  const initial = await persistent.current();
  await page.clock.install();
  await page.clock.pauseAt(new Date(Date.now() + 1000));
  await page.getByRole('textbox').fill('Local dirty draft');
  await persistent.api(`/investigations/${initial.id}/workspace`, 'PATCH', {
    expected_revision: initial.workspace.revision,
    draft: 'Remote acknowledged draft',
  });
  await page.evaluate(() => dispatchEvent(new Event('focus')));
  await expect(page.getByText('This chat changed in another tab. Your draft is unsaved.')).toBeVisible();
  await page.clock.runFor(300);
  await expect(page.getByRole('textbox')).toHaveValue('Local dirty draft');
  expect((await persistent.current()).workspace.draft).toBe('Remote acknowledged draft');
  await page.getByRole('button', { name: 'Use this draft' }).click();
  await expect(page.getByText('Draft saved', { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('textbox')).toHaveValue('Local dirty draft');
  expect((await persistent.current()).turn_count).toBe(0);
});

test('idle tab adopts another tab active turn and Stop owns that exact turn', async ({ page, context, persistent }) => {
  await persistent.login(page);
  await page.getByRole('textbox').fill('Saved draft');
  await expect(page.getByText('Draft saved', { exact: true })).toBeVisible();
  const initial = await persistent.current();
  const second = await context.newPage();
  await second.goto(persistent.origin);
  await expect(second.getByRole('textbox')).toHaveValue('Saved draft');
  await persistent.block('model');
  await second.getByRole('textbox').fill('Inspect worker');
  await second.getByRole('button', { name: 'Investigate', exact: true }).click();
  await persistent.marker('model.entered');
  const active = (await persistent.current()).active_turn_id!;
  let gets = 0;
  let observers = 0;
  let posts = 0;
  const cancelled: string[] = [];
  page.on('request', (request) => {
    const path = new URL(request.url()).pathname;
    if (path === `/api/v1/turns/${active}`) gets++;
    if (path === `/api/v1/turns/${active}/events`) observers++;
    if (request.method() === 'POST') {
      posts++;
      if (path.endsWith('/cancel')) cancelled.push(path);
    }
  });
  await page.evaluate(() => dispatchEvent(new Event('focus')));
  await expect(page.getByRole('button', { name: 'Stop diagnosis' })).toBeVisible();
  await expect.poll(() => observers).toBe(1);
  expect(gets).toBe(1);
  await page.getByRole('button', { name: 'Stop diagnosis' }).click();
  await expect(page.getByRole('heading', { name: 'Diagnosis stopped' })).toBeVisible();
  expect(cancelled).toEqual([`/api/v1/turns/${active}/cancel`]);
  expect(posts).toBe(1);
  expect((await persistent.api<{ turn_count: number }>(`/investigations/${initial.id}`)).turn_count).toBe(1);
  expect((await persistent.events()).filter((row) => row.event.startsWith('model.'))).toHaveLength(1);
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Diagnosis stopped' })).toBeVisible();
});

test('latest ten pages retain older actor-owned chats', async ({ page, persistent }) => {
  let last = '';
  for (let index = 0; index < 12; index++) {
    const id = randomUUID();
    await persistent.api('/investigations', 'POST', { id, host: 'local' });
    last = id;
  }
  await persistent.api('/me/workspace', 'PATCH', { expected_revision: 0, last_investigation_id: last, host: 'local' });
  await persistent.login(page);
  await expect(page.locator('.saved-chat:visible')).toHaveCount(10);
  await page.getByRole('button', { name: 'Older chats' }).click();
  await expect(page.locator('.saved-chat:visible')).toHaveCount(12);
  expect((await persistent.events()).filter((row) => row.event.startsWith('model.'))).toHaveLength(0);
});

test('restores acknowledged draft, model preference and exact selected identity', async ({ page, persistent }) => {
  await persistent.login(page);
  await page.getByTitle('worker', { exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Container overview', exact: true })).toBeVisible();
  const selected = { kind: 'container', id: 'a'.repeat(64), name: 'worker' };
  await expect.poll(async () => (await persistent.current()).workspace.selected_container).toEqual(selected);
  await page.getByRole('button', { name: /Choose model/ }).click();
  await page
    .getByRole('dialog', { name: 'Choose model' })
    .getByRole('button', { name: 'qwen3.5:9b', exact: true })
    .click();
  await expect
    .poll(async () => (await persistent.api<{ model: unknown }>('/me/workspace')).model)
    .toEqual({ provider: 'ollama', model: 'qwen3.5:9b' });
  const before = await persistent.current();
  await persistent.api(`/investigations/${before.id}/workspace`, 'PATCH', {
    expected_revision: before.workspace.revision,
    draft: 'Acknowledged exact-target draft',
    target: selected,
    view: 'diagnostics',
  });
  await page.reload();
  await expect(page.getByRole('textbox')).toHaveValue('Acknowledged exact-target draft');
  await expect(page.getByText('Saved container scope: worker ·')).toBeVisible();
  await expect(page.getByRole('button', { name: /Choose model/ })).toContainText('qwen3.5:9b');
  const restored = await persistent.current();
  expect(restored.workspace.target).toEqual(selected);
  expect(restored.workspace.selected_container).toEqual(selected);
  expect(restored.turn_count).toBe(0);
});

test('saved clarification survives F5 and groups its continuation under the original question', async ({
  page,
  persistent,
}) => {
  await persistent.login(page);
  const query = 'Could other-project simply be stopped?';
  await page.getByRole('textbox').fill(query);
  await page.getByRole('button', { name: 'Investigate', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Resource clarification' })).toBeVisible();
  const parent = (await persistent.current()).turns.items[0] as SavedTurn;
  expect(parent.state).toBe('awaiting_selection');
  expect((await persistent.events()).filter((row) => row.event.startsWith('model.'))).toHaveLength(0);
  await page.reload();
  await expect(page.getByRole('region', { name: 'Resource clarification' })).toBeVisible();
  await page.getByRole('button', { name: 'Docker Compose other-project', exact: true }).click();
  await expect(page.getByText('Retained worker answer', { exact: true })).toBeVisible();
  const turns = (await persistent.current()).turns.items as SavedTurn[];
  expect(turns).toHaveLength(2);
  expect(turns[0]!.resolved_by_turn_id).toBe(turns[1]!.id);
  expect(turns[1]).toMatchObject({
    clarification_of: parent.id,
    query,
    state: 'completed',
    target: { kind: 'compose', name: 'other-project' },
  });
  await page.reload();
  await expect(page.locator('.query-line h2')).toHaveText(query);
  await expect(page.getByRole('region', { name: 'Resource clarification' })).toHaveCount(0);
  await expect(page.locator('.session-turns')).toHaveCount(0);
  expect((await persistent.current()).turn_count).toBe(2);
});

test('logout revokes both tabs while accepted work continues and actors see only their own history', async ({
  page,
  context,
  browser,
  persistent,
}) => {
  await persistent.block('model');
  await persistent.login(page);
  await page.getByRole('textbox').fill('Inspect worker');
  await page.getByRole('button', { name: 'Investigate', exact: true }).click();
  await persistent.marker('model.entered');
  const chat = await persistent.current();
  const other = await context.newPage();
  await other.goto(persistent.origin);
  await expect(other.getByRole('button', { name: 'Stop diagnosis' })).toBeVisible();
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page.getByRole('heading', { name: 'Sign in to DockSight' })).toBeVisible();
  await other.reload();
  await expect(other.getByRole('heading', { name: 'Sign in to DockSight' })).toBeVisible();
  expect((await persistent.current()).active_turn_id).toBe(chat.active_turn_id);
  await persistent.release('model');
  expect((await persistent.terminal(chat.active_turn_id!)).state).toBe('completed');
  const bobContext = await browser.newContext({ locale: 'en-US' });
  try {
    const bob = await bobContext.newPage();
    await persistent.login(bob, 'bob');
    await expect(bob.locator('.query-line h2')).toHaveCount(0);
    await expect(bob.getByText('Retained worker answer', { exact: true })).toHaveCount(0);
    expect(await persistent.status(`/investigations/${chat.id}`, 'bob')).toBe(404);
    expect(await persistent.status(`/turns/${chat.active_turn_id}`, 'bob')).toBe(404);
    expect((await persistent.api<{ items: unknown[] }>('/investigations', 'GET', undefined, 'bob')).items).toHaveLength(
      1,
    );
  } finally {
    await bobContext.close();
  }
});

test('archived action waits for authoritative GET and expiration disables confirmation', async ({
  page,
  persistent,
}) => {
  await persistent.login(page);
  await persistent.targetWorker(page);
  await page.getByRole('textbox').fill('Inspect worker');
  await page.getByRole('button', { name: 'Investigate', exact: true }).click();
  await expect(page.getByText('Retained worker answer', { exact: true })).toBeVisible();
  await persistent.advanceActions(301);
  await page.reload();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  let release = () => {};
  const gate = new Promise<void>((done) => {
    release = done;
  });
  let reads = 0;
  let writes = 0;
  await page.route('**/actions/*', async (route) => {
    if (route.request().method() !== 'GET') {
      writes++;
      return route.continue();
    }
    reads++;
    const response = await route.fetch();
    await gate;
    await route.fulfill({ response });
  });
  await reviewRestart(page);
  await expect.poll(() => reads).toBe(1);
  await expect(page.getByRole('button', { name: 'Confirm restart' })).toHaveCount(0);
  release();
  await expect(page.getByRole('dialog')).toContainText('expired');
  await expect(page.getByRole('button', { name: 'Confirm restart' })).toHaveCount(0);
  expect(writes).toBe(0);
  expect((await persistent.events()).filter((row) => row.event === 'runtime.restart')).toHaveLength(0);
});

test('F5 after an execution claim reads existing state and never sends another mutation', async ({
  page,
  persistent,
}) => {
  await persistent.login(page);
  await persistent.targetWorker(page);
  await page.getByRole('textbox').fill('Inspect worker');
  await page.getByRole('button', { name: 'Investigate', exact: true }).click();
  await expect(page.getByText('Retained worker answer', { exact: true })).toBeVisible();
  await persistent.block('mutation');
  const keys: string[] = [];
  page.on('request', (request) => {
    if (request.url().endsWith('/execute')) keys.push(request.headers()['idempotency-key']!);
  });
  await reviewRestart(page);
  await expect(page.getByRole('dialog')).toContainText('a'.repeat(64));
  await page.getByRole('button', { name: 'Confirm restart' }).click();
  await persistent.marker('mutation.entered');
  expect(keys).toHaveLength(1);
  expect(keys[0]).toBeTruthy();
  await page.reload();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await reviewRestart(page);
  await expect(page.getByRole('dialog')).toContainText('running');
  await expect(page.getByRole('button', { name: 'Confirm restart' })).toHaveCount(0);
  await persistent.release('mutation');
  await expect
    .poll(async () => (await persistent.events()).filter((row) => row.event === 'runtime.restart').length)
    .toBe(1);
  await page.reload();
  await reviewRestart(page);
  await expect(page.getByRole('dialog')).toContainText('succeeded');
  expect(keys).toHaveLength(1);
});

test('controlled process death after dispatch keeps an archived action indeterminate and unavailable', async ({
  page,
  persistent,
}) => {
  await persistent.login(page);
  await persistent.targetWorker(page);
  await page.getByRole('textbox').fill('Inspect worker');
  await page.getByRole('button', { name: 'Investigate', exact: true }).click();
  await expect(page.getByText('Retained worker answer', { exact: true })).toBeVisible();
  await persistent.block('mutation');
  await reviewRestart(page);
  await page.getByRole('button', { name: 'Confirm restart' }).click();
  await persistent.marker('mutation.entered');
  await persistent.restartBackend();
  await page.reload();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await reviewRestart(page);
  await expect(page.getByRole('dialog')).toContainText('indeterminate');
  await expect(page.getByRole('button', { name: 'Confirm restart' })).toHaveCount(0);
  expect((await persistent.events()).filter((row) => row.event === 'runtime.restart')).toHaveLength(0);
});

for (const mode of ['wrong', 'unset'] as const) {
  test.describe(`proxy public origin ${mode}`, () => {
    test.use({ originMode: mode });
    test('rejects login when the public browser origin is not configured correctly', async ({ page, persistent }) => {
      await page.goto(persistent.origin);
      await page.getByRole('button', { name: 'Connect API', exact: true }).click();
      await page.getByLabel('Bearer token', { exact: true }).fill('persistence-alice-test-token-0001');
      const response = page.waitForResponse((response) => response.url().endsWith('/auth/login'));
      await page.getByRole('button', { name: 'Connect', exact: true }).click();
      expect((await response).status()).toBe(403);
      await expect(page.getByRole('dialog')).toBeVisible();
      expect(await page.context().cookies()).toEqual([]);
    });
  });
}

test.describe('approved local model', () => {
  test.use({ liveModel: true });
  test.skip(process.env.DOCKSIGHT_PERSISTENCE_LIVE !== '1', 'Set DOCKSIGHT_PERSISTENCE_LIVE=1 for owned Docker/Ollama');
  test('continues with fresh owned Docker evidence across an in-flight browser refresh', async ({
    page,
    persistent,
  }) => {
    test.setTimeout(240_000);
    await persistent.login(page);
    const container = await persistent.container();
    await persistent.targetWorker(page, { kind: 'container', id: container.id, name: container.name });
    await page
      .getByRole('textbox')
      .fill('Inspect this exact container state and recent logs. Explain only collected evidence in English.');
    await page.getByRole('button', { name: 'Investigate', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Diagnostic conclusion', exact: true })).toBeVisible({
      timeout: 110_000,
    });
    const first = (await persistent.current()).turns.items[0] as SavedTurn;
    expect(first.state).toBe('completed');
    expect(JSON.stringify(first.answer?.evidence)).toContain('Fixture revision one');
    const before = await persistent.events();
    await persistent.freshEvidence();
    await persistent.block('model');
    let submissions = 0;
    page.on('request', (request) => {
      if (request.method() === 'POST' && /\/investigations\/[^/]+\/turns$/.test(request.url())) submissions++;
    });
    await page
      .getByRole('textbox')
      .fill('Recheck this exact container after its test log changed. Explain only the fresh evidence in English.');
    await page.getByRole('button', { name: 'Investigate', exact: true }).click();
    await persistent.marker('model.entered');
    const active = (await persistent.current()).active_turn_id!;
    const inFlight = await persistent.events();
    expect(inFlight.filter((row) => row.event === 'runtime.logs').length).toBeGreaterThan(
      before.filter((row) => row.event === 'runtime.logs').length,
    );
    await page.reload();
    await expect(page.getByRole('button', { name: 'Stop diagnosis' })).toBeVisible();
    expect((await persistent.current()).active_turn_id).toBe(active);
    expect(submissions).toBe(1);
    expect((await persistent.events()).filter((row) => row.event.startsWith('model.'))).toEqual(
      inFlight.filter((row) => row.event.startsWith('model.')),
    );
    await persistent.release('model');
    await expect(page.getByRole('heading', { name: 'Diagnostic conclusion', exact: true })).toBeVisible({
      timeout: 110_000,
    });
    const second = await persistent.api<SavedTurn>(`/turns/${active}`);
    expect(second.state).toBe('completed');
    expect(second.investigation_id).toBe(first.investigation_id);
    expect(JSON.stringify(second.answer?.evidence)).toContain('Fixture revision two');
    expect(second.answer!.evidence.every((row) => row.container_id === container.id)).toBe(true);
    expect(second.answer!.evidence.every((row) => Date.parse(row.observed_at) > Date.parse(first.created_at))).toBe(
      true,
    );
    expect((await persistent.current()).turn_count).toBe(2);
    expect(submissions).toBe(1);
    expect((await persistent.events()).filter((row) => row.event === 'model.final.done')).toHaveLength(2);
    expect(
      (await persistent.events()).filter((row) => row.event === 'runtime.restart' || row.event === 'runtime.stop'),
    ).toHaveLength(0);
    const events = await persistent.events();
    const counts = Object.fromEntries(
      [...new Set(events.map((row) => row.event))].map((name) => [
        name,
        events.filter((row) => row.event === name).length,
      ]),
    );
    console.info('Owned local recovery counters:', JSON.stringify(counts));
  });
});
