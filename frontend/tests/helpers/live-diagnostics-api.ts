import { expect, type Page } from '@playwright/test';
import { demoContainer, demoSystemStatus } from '../../src/infrastructure/demo/demo';
import type { Answer, Stack, TurnEvent } from '../../src/shared/contracts/contracts';
import { routeSavedApi } from './saved-server';

const host = 'e2e';
const project = 'commerce';
const apiBase = 'http://localhost:4174/api/v1';
const token = 'browser-smoke-token';

/** Serve a deterministic healthy Compose diagnosis through the app's separate-origin API connection. */
export async function routeLiveDiagnosticsSmoke(page: Page) {
  const observedAt = '2026-11-19T12:00:00Z';
  const container = demoContainer(5, host, observedAt);
  const stack: Stack = {
    kind: 'compose',
    name: project,
    total: 1,
    running: 1,
    container_ids: [container.id],
    members: [
      {
        id: container.id,
        name: container.name,
        kind: 'container',
        state: 'running',
        total: 1,
        running: 1,
        exit_code: 0,
        health: null,
      },
    ],
  };
  const answer: Answer = {
    schema_version: 1,
    summary: 'Redis is running in the Commerce Compose project.',
    uncertain: false,
    group: { summary: stack, evidence_id: 'e1', inventory_code: null, logs: [] },
    evidence: [
      { id: 'e1', kind: 'stack', host, container_id: null, observed_at: observedAt, data: { stacks: [stack] } },
      { id: 'e2', kind: 'container', host, container_id: container.id, observed_at: observedAt, data: container },
    ],
    widgets: [
      { widget_type: 'container_status', snapshot: container, evidence_ids: ['e2'], actions: [], recommendation: null },
    ],
  };
  const envelope = { schema_version: 1, request_id: 'smoke-request', turn_id: 'smoke-turn' } as const;
  const events: TurnEvent[] = [
    { ...envelope, type: 'answer.ready', answer },
    { ...envelope, type: 'turn.completed' },
  ];

  // Hold the answer until the browser attaches its observer, so the scenario has to read the SSE result.
  const observing = page
    .waitForRequest(
      (request) =>
        request.method() === 'GET' && /^\/api\/v1\/turns\/[^/]+\/events$/.test(new URL(request.url()).pathname),
      { timeout: 15_000 },
    )
    .then(
      () => true,
      () => false,
    );
  await routeSavedApi(page, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === '/api/v1/hosts') return route.fulfill({ json: [{ id: host, name: 'Live E2E' }] });
    if (url.pathname === '/api/v1/system/status')
      return route.fulfill({ json: demoSystemStatus(url.searchParams.get('host')) });
    if (url.pathname === '/api/v1/containers') return route.fulfill({ json: [container] });
    if (url.pathname === '/api/v1/stacks') return route.fulfill({ json: [stack] });
    if (request.method() === 'POST' && /^\/api\/v1\/investigations\/[^/]+\/turns$/.test(url.pathname)) {
      expect(request.headers()['authorization']).toBe(`Bearer ${token}`);
      expect(await observing, 'The browser opens the saved turn SSE stream').toBe(true);
      return route.fulfill({ body: events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join('') });
    }
    return route.fulfill({ status: 404, json: { code: 'not_found', message: 'Unconfigured fixture route' } });
  });

  return { apiBase, token, project };
}
