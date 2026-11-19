import { writeFile } from 'node:fs/promises';
import { expect, test, type Locator, type Page } from '@playwright/test';
import type { Answer } from '../src/shared/contracts/contracts';
import {
  acceptedTurnSchema,
  savedTurnSchema,
  startTurnSchema,
  type SavedTurn,
  type StartTurn,
} from '../src/shared/contracts/investigation-contracts';
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
    diagnosticResponses: Record<string, { body: string; stream: boolean }[]>;
  }
}

/** Copy saved turn reads and streams before Chrome can evict their consumed response bodies. */
async function captureTurnResponses(page: Page) {
  await page.addInitScript(() => {
    const captured = window;
    captured.diagnosticResponses = {};
    const fetch = window.fetch.bind(window);
    window.fetch = async (...args) => {
      const response = await fetch(...args);
      const path = new URL(response.url).pathname.match(/^\/api\/v1\/turns\/([\da-f-]+)(\/events)?$/);
      if (path && response.ok) {
        const id = path[1]!;
        void response
          .clone()
          .text()
          .then(
            (body) => {
              (captured.diagnosticResponses[id] ??= []).push({ body, stream: Boolean(path[2]) });
            },
            () => undefined,
          );
      }
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
    exitCode: 'Exit code',
    oomKilled: 'OOM killed',
    restarts: 'Restarts',
    observationId: 'Observation ID',
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
    exitCode: 'Код выхода',
    oomKilled: 'Убит из-за OOM',
    restarts: 'Перезапуски',
    observationId: 'ID наблюдения',
  },
};

/** Record exactly the saved question or clarification admitted by the server. */
async function submitTurn(page: Page, button: Locator) {
  const [response] = await Promise.all([
    page.waitForResponse(
      (value) =>
        value.request().method() === 'POST' &&
        /^\/api\/v1\/investigations\/[^/]+\/turns$/.test(new URL(value.url()).pathname),
      { timeout: 15_000 },
    ),
    button.click({ timeout: 15_000 }),
  ]);
  expect(response.status()).toBe(202);
  const payload = startTurnSchema.parse(response.request().postDataJSON());
  const { snapshot, created } = acceptedTurnSchema.parse(await response.json());
  expect(created).toBe(true);
  expect(snapshot.submission_id).toBe(payload.submission_id);
  return { payload, snapshot };
}

/** Read a terminal revision from the browser's observer or its initial read for fast turns. */
async function readTurn(page: Page, accepted: SavedTurn): Promise<SavedTurn> {
  if (accepted.state !== 'running') return accepted;
  let terminal: SavedTurn | undefined;
  await expect
    .poll(
      async () => {
        const responses = await page.evaluate((id) => window.diagnosticResponses[id] ?? [], accepted.id);
        const snapshots = responses.flatMap(({ body, stream }) =>
          stream
            ? body
                .split(/\r?\n/)
                .filter((line) => line.startsWith('data: '))
                .map((line) => line.slice(6))
            : [body],
        );
        terminal = snapshots
          .map((snapshot) => savedTurnSchema.parse(JSON.parse(snapshot)))
          .find((snapshot) => snapshot.state !== 'running');
        return terminal?.state;
      },
      { timeout: 245_000, message: `Wait for a terminal revision of saved turn ${accepted.id}` },
    )
    .toBeDefined();
  expect(terminal!.id).toBe(accepted.id);
  return terminal!;
}

/** Select an observed ambiguous group and verify that its exact identity continues the original question. */
async function clarifyGroup(page: Page, parent: SavedTurn, scenario: Input, label: string) {
  expect(parent.state, parent.error?.message).toBe('awaiting_selection');
  expect(parent.answer).toBeNull();
  expect(parent.selection?.candidates.map((row) => `${row.kind}:${row.name}`).sort()).toEqual(
    [`compose:${scenario.project}`, `compose:${scenario.peer_project}`].sort(),
  );
  const panel = page.getByRole('region', { name: label, exact: true });
  await expect(panel.getByRole('button')).toHaveCount(2);
  await expect(page.locator('.widget-container_status')).toHaveCount(0);
  const admitted = await submitTurn(
    page,
    panel.getByRole('button', { name: `Docker Compose ${scenario.project}`, exact: true }),
  );
  expect(admitted.payload).toMatchObject({
    kind: 'clarification',
    clarification_of: parent.id,
    expected_parent_revision: parent.revision,
    target: { kind: 'compose', name: scenario.project },
  });
  expect(admitted.snapshot.clarification_of).toBe(parent.id);
  expect(admitted.snapshot.investigation_id).toBe(parent.investigation_id);
  expect(admitted.snapshot.query).toBe(scenario.query);
  return admitted;
}

/** Check rendered observations against public response data, including exact evidence navigation. */
async function checkCards(page: Page, answer: Answer, locale: 'en' | 'ru') {
  const labels = copy[locale];
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
    await expect(view.getByText(card.snapshot.image, { exact: true })).toBeVisible();
    const oomKilled = card.snapshot.oom_killed ? (locale === 'ru' ? 'Да' : 'Yes') : locale === 'ru' ? 'Нет' : 'No';
    const facts = [
      [labels.exitCode, String(card.snapshot.exit_code)],
      [labels.oomKilled, oomKilled],
      [labels.restarts, String(card.snapshot.restart_count)],
    ] as const;
    for (const [label, value] of facts) {
      const fact = view.locator('dl > div').filter({ has: page.getByText(label, { exact: true }) });
      await expect(fact.locator('dd')).toHaveText(value);
    }
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
    const identity = details
      .locator('p')
      .filter({ has: page.getByText(labels.observationId, { exact: true }) })
      .locator('code');
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
  let turn: SavedTurn | undefined;
  let clarification: SavedTurn | undefined;
  let payload: StartTurn | undefined;
  try {
    await captureTurnResponses(page);
    await page.goto('/');
    const language = page.getByRole('combobox', { name: 'Language', exact: true });
    await expect(language).toBeVisible();
    await chooseOption(language, locale);
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
    const admitted = await submitTurn(
      page,
      page.getByRole('button', {
        name: scenario.explicit ? labels.diagnose : labels.investigate,
        exact: true,
      }),
    );
    payload = admitted.payload;
    expect(payload.kind).toBe('question');
    expect(admitted.snapshot.host).toBe('e2e');
    expect(payload.target).toEqual(scenario.explicit ? { kind: 'compose', name: scenario.project } : null);
    turn = await readTurn(page, admitted.snapshot);
    if (scenario.clarify) {
      clarification = turn;
      const continued = await clarifyGroup(page, clarification, scenario, labels.clarification);
      payload = continued.payload;
      turn = await readTurn(page, continued.snapshot);
    }
    expect(turn.state, turn.error?.message).toBe('completed');
    expect(turn.selection).toBeNull();
    expect(turn.answer).not.toBeNull();
    const answer = turn.answer!;
    await expect(page.locator('.conclusion > p').first()).toHaveText(answer.summary);
    const report = page.getByRole('region', {
      name: scenario.host_overview ? labels.hostOverview : labels.report,
      exact: true,
    });
    const memberRows = scenario.host_overview ? report.getByRole('article') : report.locator('.group-member');
    const members = scenario.host_overview ? answer.host_overview!.members : answer.group!.summary.members;
    expect(members).toBeDefined();
    const memberCount = members!.length;
    if (scenario.host_overview) {
      expect(answer.host_overview).toBeTruthy();
      expect(answer.group).toBeNull();
      await expect(page.getByRole('region', { name: labels.report, exact: true })).toHaveCount(0);
      await expect(report).toContainText('e2e');
      await report.getByRole('button', { name: locale === 'ru' ? 'Источник' : 'Source', exact: true }).click();
      await expect(page.locator('#evidence-observation')).toBeFocused();
      await expect(page.locator('#evidence-observation')).toContainText(
        locale === 'ru' ? 'Список контейнеров хоста Docker' : 'Docker host inventory',
      );
    } else await expect(report).toContainText(scenario.project);
    await expect(memberRows).toHaveCount(memberCount);
    await checkCards(page, answer, locale);
    const sources = page.getByRole('region', { name: labels.sources, exact: true });
    for (const card of answer.widgets.filter((row) => row.widget_type === 'container_status')) {
      await expect(sources.getByRole('group', { name: card.snapshot.name, exact: true })).toBeVisible();
    }
    await chooseOption(scope, 'all');
    await expect(memberRows).toHaveCount(memberCount);
    await expect(page.locator('.widget-container_status')).toHaveCount(
      answer.widgets.filter((row) => row.widget_type === 'container_status').length,
    );
  } finally {
    await writeFile(scenario.output, JSON.stringify({ input: payload, turn, clarification }, null, 2), 'utf8');
    await page.screenshot({ path: scenario.output.replace(/\.json$/, '.png'), fullPage: true });
  }
});
