import { writeFile } from 'node:fs/promises';
import { expect, test, type Page, type Response } from '@playwright/test';
import { answerSchema, targetSelectionSchema, type Answer, type TurnInput } from '../src/contracts';
import { chooseOption } from '../tests/helpers/select';

interface Input {
  project: string;
  explicit: boolean;
  clarify: boolean;
  host_overview: boolean;
  peer_project: string;
  language: 'en' | 'ru';
  query: string;
  output: string;
}

declare global {
  interface Window {
    diagnosticStreams: Promise<string>[];
  }
}

/** Observe actual SSE bodies in the page because Chrome can evict a consumed streaming response from CDP. */
async function captureStreams(page: Page) {
  await page.addInitScript(() => {
    const captured = window;
    captured.diagnosticStreams = [];
    const fetch = window.fetch.bind(window);
    window.fetch = async (...args) => {
      const response = await fetch(...args);
      if (new URL(response.url).pathname === '/api/v1/chat/turns')
        captured.diagnosticStreams.push(response.clone().text());
      return response;
    };
  });
}

const input: Input | undefined = process.env.DOCKSIGHT_E2E_BROWSER_INPUT
  ? (JSON.parse(process.env.DOCKSIGHT_E2E_BROWSER_INPUT) as Input)
  : undefined;
test.skip(!input, 'Run through pytest with --live-e2e --e2e-browser; no external calls by default.');

const copy = {
  en: {
    connectApi: 'Connect API',
    connect: 'Connect',
    token: 'Bearer token',
    endpoint: 'API base URL',
    scope: 'Investigation scope',
    group: 'Group',
    diagnose: 'Diagnose group',
    investigate: 'Investigate',
    report: 'Group observations',
    hostOverview: 'Host overview',
    sources: 'Observation sources',
    clarification: 'Group clarification',
  },
  ru: {
    connectApi: 'Подключить API',
    connect: 'Подключить',
    token: 'Bearer-токен',
    endpoint: 'Базовый адрес API',
    scope: 'Область диагностики',
    group: 'Группа',
    diagnose: 'Диагностировать группу',
    investigate: 'Исследовать',
    report: 'Наблюдения группы',
    hostOverview: 'Обзор хоста',
    sources: 'Источники наблюдений по ресурсам',
    clarification: 'Уточнение группы',
  },
};

/** Decode the same public SSE response consumed by the client without mocking transport or model output. */
async function readEvents(page: Page, response: Response): Promise<Record<string, unknown>[]> {
  expect(response.ok()).toBe(true);
  await expect.poll(() => page.evaluate(() => window.diagnosticStreams.length)).toBeGreaterThan(0);
  return page.evaluate(async () => {
    const body = window.diagnosticStreams.shift();
    if (!body) throw new Error('The browser did not capture the diagnostic stream.');
    return (await body)
      .split(/\r?\n/)
      .filter((line) => line.startsWith('data: '))
      .map((line) => JSON.parse(line.slice(6)) as Record<string, unknown>);
  });
}

/** Select an observed ambiguous group and verify that its exact identity continues the original question. */
async function clarifyGroup(page: Page, events: Record<string, unknown>[], scenario: Input, label: string) {
  const choices = events.filter((event) => event.type === 'clarification.required');
  expect(choices).toHaveLength(1);
  expect(events.some((event) => event.type === 'answer.ready' || event.type === 'turn.failed')).toBe(false);
  const selection = targetSelectionSchema.parse(choices[0]!.selection);
  expect(selection.candidates.map((row) => `${row.kind}:${row.name}`).sort()).toEqual(
    [`compose:${scenario.project}`, `compose:${scenario.peer_project}`].sort(),
  );
  const panel = page.getByRole('region', { name: label, exact: true });
  await expect(panel.getByRole('button')).toHaveCount(2);
  await expect(page.locator('.widget-container_status')).toHaveCount(0);
  const pending = page.waitForResponse(
    (response) => response.request().method() === 'POST' && new URL(response.url()).pathname === '/api/v1/chat/turns',
  );
  await panel.getByRole('button', { name: `Docker Compose ${scenario.project}`, exact: true }).click();
  const response = await pending;
  const payload = response.request().postDataJSON() as TurnInput;
  expect(payload.query).toBe(scenario.query);
  expect(payload.group).toEqual({ kind: 'compose', name: scenario.project });
  return { payload, events: await readEvents(page, response) };
}

/** Check rendered observations against public response data, including exact evidence navigation. */
async function checkCards(page: Page, answer: Answer, locale: 'en' | 'ru') {
  const states = answer.widgets.filter((card) => card.widget_type === 'container_status');
  const logs = answer.widgets.filter((card) => card.widget_type === 'log_anomalies');
  await expect(page.locator('.widget-container_status')).toHaveCount(states.length);
  await expect(page.locator('.widget-log_anomalies')).toHaveCount(logs.length);
  for (const card of states) {
    const panel = page
      .locator('.container-evidence')
      .filter({ has: page.getByRole('heading', { name: card.snapshot.name, exact: true }) });
    await expect(panel).toBeVisible();
    const view = panel.locator('.widget-container_status');
    await expect(view.locator('.image-name code')).toHaveText(card.snapshot.image);
    await expect(view.locator('.fact-strip dd').first()).toHaveText(String(card.snapshot.exit_code));
    await expect(view.locator('.fact-strip dd').nth(1)).toHaveText(
      card.snapshot.oom_killed ? (locale === 'ru' ? 'Да' : 'Yes') : locale === 'ru' ? 'Нет' : 'No',
    );
    await expect(view.locator('.fact-strip dd').nth(2)).toHaveText(String(card.snapshot.restart_count));
  }
  for (const card of logs) {
    const member =
      answer.host_overview?.members.find((row) => row.container_id === card.container_id) ??
      answer.group?.summary.members?.find((row) => row.id === card.container_id);
    expect(member).toBeDefined();
    const panel = page
      .locator('.container-evidence')
      .filter({ has: page.getByRole('heading', { name: member!.name, exact: true }) });
    const view = panel.locator('.widget-log_anomalies');
    expect(await view.locator('.log-line code').allTextContents()).toEqual(card.logs.entries.map((row) => row.message));
    await view.locator('.source-link').click();
    const observation = page.locator('#evidence-observation');
    await expect(observation).toBeFocused();
    const details = observation.locator('details');
    if ((await details.getAttribute('open')) === null) await details.locator('summary').click();
    const identity = observation.locator('.evidence-id code');
    await expect(identity).toHaveText(/^e\d+$/, { useInnerText: true });
    const id = await identity.innerText();
    const source = answer.evidence.find((row) => row.id === id)!;
    expect(card.evidence_ids).toContain(id);
    expect(source.kind).toBe('logs');
    expect(source.container_id).toBe(card.container_id);
    expect(source.host).toBe('e2e');
    await expect(observation.locator('.raw-evidence pre')).toBeVisible();
    expect(JSON.parse((await observation.locator('.raw-evidence pre').textContent())!)).toEqual(source.data);
    await expect(observation.locator('time')).toHaveAttribute('datetime', source.observed_at);
    await expect(observation).toContainText(member!.name);
  }
}

test('shows scoped host or group observations from the real backend', async ({ page }) => {
  const scenario = input!;
  // Free chat deliberately uses a different interface locale from the question's language.
  const locale = scenario.explicit ? scenario.language : scenario.language === 'ru' ? 'en' : 'ru';
  const labels = copy[locale];
  let events: Record<string, unknown>[] = [];
  let clarificationEvents: Record<string, unknown>[] = [];
  let payload: TurnInput | undefined;
  try {
    await captureStreams(page);
    await page.goto('/');
    await chooseOption(page.locator('.language-switch [role="combobox"]'), locale);
    await page.getByRole('button', { name: labels.connectApi, exact: true }).click();
    await page.getByLabel(labels.endpoint, { exact: true }).fill(`${process.env.DOCKSIGHT_E2E_API}/api/v1`);
    await page.getByLabel(labels.token, { exact: true }).fill(process.env.DOCKSIGHT_E2E_TOKEN!);
    await page.getByRole('button', { name: labels.connect, exact: true }).click();
    await expect(page.locator('.composer-foot')).toContainText('e2e');
    const scope = page.getByRole('combobox', { name: labels.scope, exact: true });
    if (scenario.explicit) {
      await chooseOption(scope, 'compose');
      await chooseOption(page.getByRole('combobox', { name: labels.group, exact: true }), scenario.project);
    } else {
      await expect(scope).toContainText(locale === 'ru' ? 'Автоматически' : 'Automatic');
      await page.locator('#query').fill(scenario.query);
    }
    const pending = page.waitForResponse(
      (response) => response.request().method() === 'POST' && new URL(response.url()).pathname === '/api/v1/chat/turns',
    );
    await page
      .getByRole('button', {
        name: scenario.explicit ? labels.diagnose : labels.investigate,
        exact: true,
      })
      .click();
    const response = await pending;
    payload = response.request().postDataJSON() as TurnInput;
    expect(payload.host).toBe('e2e');
    expect(payload.group).toEqual(scenario.explicit ? { kind: 'compose', name: scenario.project } : undefined);
    events = await readEvents(page, response);
    if (scenario.clarify) {
      clarificationEvents = events;
      const continued = await clarifyGroup(page, events, scenario, labels.clarification);
      events = continued.events;
      payload = continued.payload;
    }
    expect(events.filter((row) => row.type === 'turn.failed')).toEqual([]);
    expect(events.at(-1)?.type).toBe('turn.completed');
    const ready = events.filter((row) => row.type === 'answer.ready');
    expect(ready).toHaveLength(1);
    const answer = answerSchema.parse(ready[0]!.answer);
    await expect(page.locator('.conclusion > p').first()).toHaveText(answer.summary);
    const report = page.getByRole('region', {
      name: scenario.host_overview ? labels.hostOverview : labels.report,
      exact: true,
    });
    const memberSelector = scenario.host_overview ? '.host-member' : '.group-member';
    const members = scenario.host_overview ? answer.host_overview!.members : answer.group!.summary.members;
    expect(members).toBeDefined();
    const memberCount = members!.length;
    if (scenario.host_overview) {
      expect(answer.host_overview).toBeTruthy();
      expect(answer.group).toBeNull();
      expect(events.some((event) => event.type === 'clarification.required')).toBe(false);
      await expect(page.getByRole('region', { name: labels.report, exact: true })).toHaveCount(0);
      await expect(report).toContainText('e2e');
      await report.getByRole('button', { name: locale === 'ru' ? 'Источник' : 'Source', exact: true }).click();
      await expect(page.locator('#evidence-observation')).toBeFocused();
      await expect(page.locator('#evidence-observation')).toContainText(
        locale === 'ru' ? 'Список контейнеров хоста Docker' : 'Docker host inventory',
      );
    } else await expect(report).toContainText(scenario.project);
    await expect(report.locator(memberSelector)).toHaveCount(memberCount);
    await checkCards(page, answer, locale);
    const sources = page.getByRole('region', { name: labels.sources, exact: true });
    for (const card of answer.widgets.filter((row) => row.widget_type === 'container_status')) {
      await expect(sources.getByRole('group', { name: card.snapshot.name, exact: true })).toBeVisible();
    }
    await chooseOption(scope, 'all');
    await expect(report.locator(memberSelector)).toHaveCount(memberCount);
    await expect(page.locator('.widget-container_status')).toHaveCount(
      answer.widgets.filter((row) => row.widget_type === 'container_status').length,
    );
  } finally {
    await writeFile(
      scenario.output,
      JSON.stringify({ input: payload, events, clarification_events: clarificationEvents }, null, 2),
      'utf8',
    );
    await page.screenshot({ path: scenario.output.replace(/\.json$/, '.png'), fullPage: true });
  }
});
