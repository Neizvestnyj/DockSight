import { randomUUID } from 'node:crypto';
import type { Page, Route } from '@playwright/test';
import {
  startTurnSchema,
  type ActorWorkspace,
  type InvestigationDetail,
  type SavedTurn,
} from '../../src/investigation-contracts';
import type { TurnEvent } from '../../src/contracts';

type Scenario = (route: Route) => unknown | Promise<unknown>;

/** Adapt deterministic diagnostic event fixtures into the saved HTTP protocol without a legacy request. */
export async function routeSavedApi(page: Page, scenario: Scenario) {
  const now = new Date().toISOString();
  const csrf = 'c'.repeat(43);
  const chats = new Map<string, InvestigationDetail>();
  const work = new Map<string, Promise<void>>();
  let principal = false;
  let actor: ActorWorkspace = { revision: 0, host: null, model: null, last_investigation_id: null };
  let releaseHosts: () => void = () => {};
  const hostsReady = new Promise<void>((resolve) => {
    releaseHosts = resolve;
  });

  /** Create a server fixture archive for the configured host, keeping prior chat IDs intact. */
  function create(id: string, host: string) {
    const chat: InvestigationDetail = {
      id,
      host,
      title: '',
      created_at: now,
      updated_at: now,
      active_turn_id: null,
      turn_count: 0,
      workspace: { revision: 0, draft: '', target: null, selected_container: null, view: 'diagnostics' },
      turns: { items: [], next_cursor: null },
    };
    chats.set(id, chat);
    return chat;
  }

  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();
    if (path.endsWith('/auth/session'))
      return route.fulfill(
        principal
          ? { json: { actor: 'operator', expires_at: '2026-12-01T12:00:00Z', csrf_token: csrf } }
          : { status: 401, json: { code: 'unauthorized', message: 'Sign in' } },
      );
    if (path.endsWith('/auth/login')) {
      principal = true;
      return route.fulfill({ json: { actor: 'operator', expires_at: '2026-12-01T12:00:00Z', csrf_token: csrf } });
    }
    if (path.endsWith('/auth/logout')) {
      principal = false;
      return route.fulfill({ status: 204 });
    }
    if (path.endsWith('/me/workspace')) {
      await hostsReady;
      if (method === 'PATCH') {
        const { expected_revision: _revision, ...changes } = request.postDataJSON();
        void _revision;
        actor = { ...actor, ...changes, revision: actor.revision + 1 };
      }
      return route.fulfill({ json: actor });
    }
    if (path === '/api/v1/investigations') {
      if (method === 'POST') {
        const input = request.postDataJSON() as { id: string; host: string };
        const { turns: _turns, ...view } = create(input.id, input.host);
        void _turns;
        return route.fulfill({ status: 201, json: view });
      }
      return route.fulfill({
        json: {
          items: [...chats.values()].map(({ workspace: _workspace, turns: _turns, ...summary }) => {
            void _workspace;
            void _turns;
            return summary;
          }),
          next_cursor: null,
        },
      });
    }
    if (path.startsWith('/api/v1/investigations/')) {
      const id = path.split('/')[4]!;
      const chat = chats.get(id);
      if (!chat)
        return route.fulfill({ status: 404, json: { code: 'history_not_found', message: 'History not found' } });
      if (method === 'DELETE') {
        chats.delete(id);
        return route.fulfill({ status: 204 });
      }
      if (path.endsWith('/workspace')) {
        const { expected_revision, ...patch } = request.postDataJSON();
        if (expected_revision !== chat.workspace.revision)
          return route.fulfill({
            status: 409,
            json: { code: 'workspace_conflict', message: 'Workspace changed', current: chat.workspace },
          });
        chat.workspace = { ...chat.workspace, ...patch, revision: chat.workspace.revision + 1 };
        return route.fulfill({ json: chat.workspace });
      }
      if (path.endsWith('/turns') && method === 'POST') {
        const input = startTurnSchema.parse(request.postDataJSON());
        const parent =
          input.kind === 'clarification'
            ? chat.turns.items.find((row): row is SavedTurn => 'state' in row && row.id === input.clarification_of)
            : undefined;
        const turn: SavedTurn = {
          schema_version: 1,
          id: randomUUID(),
          investigation_id: id,
          actor: 'operator',
          host: chat.host,
          submission_id: input.submission_id,
          request_id: 'fixture-origin',
          query: input.kind === 'question' ? input.query : parent!.query,
          target: input.target,
          model: input.model,
          clarification_of: parent?.id ?? null,
          resolved_by_turn_id: null,
          state: 'running',
          revision: 0,
          created_at: now,
          updated_at: now,
          finished_at: null,
          progress: [],
          progress_truncated: false,
          trace: [],
          answer: null,
          selection: null,
          error: null,
        };
        if (parent) {
          parent.resolved_by_turn_id = turn.id;
          parent.revision++;
        }
        chat.turns.items.push(turn);
        chat.title = chat.title || turn.query.slice(0, 120);
        chat.turn_count++;
        chat.active_turn_id = turn.id;
        chat.workspace = {
          ...chat.workspace,
          revision: chat.workspace.revision + 1,
          draft: parent ? chat.workspace.draft : '',
          target: turn.target,
        };
        actor = { ...actor, revision: actor.revision + 1, last_investigation_id: id };
        let finish: () => void = () => {};
        work.set(
          turn.id,
          new Promise<void>((resolve) => {
            finish = resolve;
          }),
        );
        await route.fulfill({ status: 202, json: { snapshot: turn, created: true } });
        const facade = new Proxy(route, {
          get(target, property) {
            if (property === 'fulfill')
              return async (options: { body?: string; json?: unknown }) => {
                if (options.body) applyEvents(turn, options.body);
                if (turn.state !== 'running') chat.active_turn_id = null;
              };
            if (property === 'abort')
              return async () => {
                turn.state = 'failed';
                turn.error = { code: 'connection_error', message: 'Fixture diagnostic response unavailable' };
                turn.revision++;
                chat.active_turn_id = null;
              };
            const value: unknown = Reflect.get(target, property);
            return typeof value === 'function' ? value.bind(target) : value;
          },
        });
        try {
          await scenario(facade);
        } finally {
          finish();
        }
        return;
      }
      return route.fulfill({ json: path.endsWith('/turns') ? chat.turns : chat });
    }
    if (path.startsWith('/api/v1/turns/')) {
      const turnId = path.split('/')[4]!;
      const chat = [...chats.values()].find((value) => value.turns.items.some((row) => row.id === turnId));
      const turn = chat?.turns.items.find((row): row is SavedTurn => 'state' in row && row.id === turnId);
      if (!turn)
        return route.fulfill({ status: 404, json: { code: 'history_not_found', message: 'History not found' } });
      if (path.endsWith('/cancel')) {
        turn.state = 'stopped';
        turn.revision++;
        return route.fulfill({ json: turn });
      }
      if (path.endsWith('/events')) {
        await work.get(turnId);
        return route.fulfill({
          contentType: 'text/event-stream',
          body: `event: turn.snapshot\nid: ${turn.revision}\ndata: ${JSON.stringify(turn)}\n\n`,
        });
      }
      return route.fulfill({ json: turn });
    }
    const facade = new Proxy(route, {
      get(target, property) {
        if (property === 'fulfill' && path.endsWith('/hosts'))
          return async (options: { json?: { id: string }[] }) => {
            if (!actor.last_investigation_id) {
              const host = options.json?.[0]?.id ?? 'test-host';
              const chat = create(randomUUID(), host);
              actor = { ...actor, host, last_investigation_id: chat.id };
            }
            releaseHosts();
            return route.fulfill(options);
          };
        if (property === 'abort' && path.endsWith('/hosts'))
          return async (...args: Parameters<Route['abort']>) => {
            if (!actor.last_investigation_id) {
              const chat = create(randomUUID(), 'test-host');
              actor = { ...actor, host: chat.host, last_investigation_id: chat.id };
            }
            releaseHosts();
            return route.abort(...args);
          };
        const value: unknown = Reflect.get(target, property);
        return typeof value === 'function' ? value.bind(target) : value;
      },
    });
    return scenario(facade);
  });
  return {
    /** Finish an already accepted fixture turn independently of its disconnected observer. */
    failRunning(error: NonNullable<SavedTurn['error']>) {
      for (const chat of chats.values())
        for (const row of chat.turns.items) {
          if ('state' in row && row.state === 'running') {
            row.state = 'failed';
            row.error = error;
            row.revision++;
            chat.active_turn_id = null;
          }
        }
    },
  };
}

/** Project deterministic safe model/runtime events into a full committed snapshot fixture. */
function applyEvents(turn: SavedTurn, body: string) {
  for (const frame of body.replace(/\r\n/g, '\n').split('\n\n')) {
    const text = frame
      .split('\n')
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).trimStart())
      .join('\n');
    if (!text) continue;
    const event = JSON.parse(text) as TurnEvent;
    turn.request_id = event.request_id;
    turn.revision++;
    switch (event.type) {
      case 'answer.ready':
        turn.answer = event.answer;
        break;
      case 'clarification.required':
        turn.selection = event.selection;
        break;
      case 'trace.step':
        turn.trace = [
          ...turn.trace.filter((step) => step.id !== event.step.id),
          { ...event.step, response: null, response_truncated: false },
        ];
        break;
      case 'trace.started':
        if (event.provider && event.model)
          turn.model = { provider: event.provider as NonNullable<SavedTurn['model']>['provider'], model: event.model };
        break;
      case 'tool.started':
        turn.progress.push({ tool: event.tool, state: 'running' });
        break;
      case 'tool.completed': {
        const step = turn.progress.find((row) => row.tool === event.tool && row.state === 'running');
        if (step) step.state = event.ok ? 'succeeded' : 'failed';
        break;
      }
      case 'turn.failed':
        turn.state = 'failed';
        turn.error = { code: event.code, message: event.message };
        break;
      case 'turn.completed':
        turn.state = turn.selection ? 'awaiting_selection' : 'completed';
        break;
    }
  }
  turn.finished_at = turn.updated_at;
}
