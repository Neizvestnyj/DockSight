import { randomUUID } from 'node:crypto';
import type { Page } from '@playwright/test';
import { demoAnswer, demoContainer, demoSystemStatus } from '../../src/demo';
import type { ActorWorkspace, InvestigationDetail, SavedTurn, StartTurn } from '../../src/investigation-contracts';

/** Supply HTTP contract fixtures only; this helper does not prove database persistence. */
export async function savedApi(page: Page) {
  const now = new Date().toISOString();
  const answer = demoAnswer('crash_loop', 'local');
  const action = answer.widgets.find((row) => row.widget_type === 'container_status')!.actions[0]!;
  const chats: InvestigationDetail[] = Array.from({ length: 12 }, (_, index) => {
    const id = randomUUID();
    const turn: SavedTurn = {
      schema_version: 1,
      id: randomUUID(),
      investigation_id: id,
      actor: 'operator',
      host: 'local',
      submission_id: randomUUID(),
      request_id: `saved-request-${index}`,
      query: `Archived question ${index + 1}`,
      target: null,
      model: null,
      clarification_of: null,
      resolved_by_turn_id: null,
      state: 'completed',
      revision: 8,
      created_at: now,
      updated_at: now,
      finished_at: now,
      progress: [],
      progress_truncated: false,
      trace: [],
      answer,
      selection: null,
      error: null,
    };
    return {
      id,
      host: 'local',
      title: turn.query,
      created_at: now,
      updated_at: now,
      active_turn_id: null,
      turn_count: 1,
      workspace: {
        revision: 2,
        draft: index === 0 ? 'Acknowledged draft' : '',
        target: null,
        selected_container: null,
        view: 'diagnostics',
      },
      turns: { items: [turn], next_cursor: null },
    };
  });
  let actor: ActorWorkspace = { revision: 1, last_investigation_id: chats[0]!.id, host: 'local', model: null };
  const state = {
    chats,
    actor,
    conflictNext: false,
    action: { ...action },
    submissions: [] as StartTurn[],
    mutations: 0,
    reads: [] as string[],
    signedIn: true,
  };
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace('/api/v1', '');
    const query = new URL(request.url()).searchParams;
    const method = request.method();
    state.reads.push(`${method} ${path}`);
    if (path === '/auth/session' || path === '/auth/login')
      return route.fulfill(
        state.signedIn || path === '/auth/login'
          ? { json: { actor: 'operator', expires_at: '2026-12-01T12:00:00Z', csrf_token: 'c'.repeat(43) } }
          : { status: 401, json: { code: 'unauthorized', message: 'Sign in' } },
      );
    if (path === '/auth/logout') {
      state.signedIn = false;
      return route.fulfill({ status: 204 });
    }
    if (path === '/hosts') return route.fulfill({ json: [{ id: 'local', name: 'Local test' }] });
    if (path === '/system/status') return route.fulfill({ json: demoSystemStatus(query.get('host')) });
    if (path.endsWith('/containers')) return route.fulfill({ json: [demoContainer(0, 'local', now)] });
    if (path.startsWith('/hosts/local/containers/')) return route.fulfill({ json: demoContainer(0, 'local', now) });
    if (path === '/me/workspace') {
      if (method === 'PATCH') {
        const { expected_revision: _revision, ...patch } = request.postDataJSON();
        void _revision;
        actor = { ...actor, ...patch, revision: actor.revision + 1 };
        state.actor = actor;
      }
      return route.fulfill({ json: actor });
    }
    if (path === '/investigations' && method === 'GET')
      return route.fulfill({
        json: {
          items: (query.has('before') ? chats.slice(10) : chats.slice(0, 10)).map(
            ({ workspace: _workspace, turns: _turns, ...summary }) => {
              void _workspace;
              void _turns;
              return summary;
            },
          ),
          next_cursor: query.has('before') ? null : 'older-owned-page',
        },
      });
    if (path === '/investigations' && method === 'POST') {
      const input = request.postDataJSON() as { id: string; host: string };
      const chat = {
        ...chats[0]!,
        ...input,
        title: '',
        active_turn_id: null,
        turn_count: 0,
        workspace: { revision: 0, draft: '', target: null, selected_container: null, view: 'diagnostics' as const },
        turns: { items: [], next_cursor: null },
      };
      chats.unshift(chat);
      const { turns: _turns, ...view } = chat;
      void _turns;
      return route.fulfill({ status: 201, json: view });
    }
    const chatId = path.split('/')[2];
    const chat = chats.find((row) => row.id === chatId);
    if (chat && path.endsWith('/workspace')) {
      const { expected_revision, ...patch } = request.postDataJSON();
      if (state.conflictNext || expected_revision !== chat.workspace.revision) {
        state.conflictNext = false;
        chat.workspace = { ...chat.workspace, revision: chat.workspace.revision + 1, draft: 'Another tab draft' };
        return route.fulfill({
          status: 409,
          json: {
            code: 'workspace_conflict',
            message: 'Workspace changed',
            request_id: 'conflict-read',
            current: chat.workspace,
          },
        });
      }
      chat.workspace = { ...chat.workspace, ...patch, revision: chat.workspace.revision + 1 };
      return route.fulfill({ json: chat.workspace });
    }
    if (chat && path.endsWith('/turns') && method === 'POST') {
      const input = request.postDataJSON() as StartTurn;
      state.submissions.push(input);
      const turn: SavedTurn = {
        ...(chats[1]!.turns.items[0] as SavedTurn),
        id: randomUUID(),
        investigation_id: chat.id,
        submission_id: input.submission_id,
        query: input.kind === 'question' ? input.query : 'Original question',
        target: input.target,
        revision: 2,
        request_id: 'new-originating-request',
      };
      chat.turns.items.push(turn);
      chat.workspace = { ...chat.workspace, draft: '', revision: chat.workspace.revision + 1 };
      chat.turn_count++;
      return route.fulfill({ status: 202, json: { snapshot: turn, created: true } });
    }
    if (chat && method === 'DELETE') {
      chats.splice(chats.indexOf(chat), 1);
      return route.fulfill({ status: 204 });
    }
    if (chat) return route.fulfill({ json: chat });
    if (path.includes('/actions/') && method === 'GET') return route.fulfill({ json: state.action });
    if (path.endsWith('/execute')) {
      state.mutations++;
      state.action = { ...state.action, state: 'succeeded', message: 'Executed once' };
      return route.fulfill({ json: state.action });
    }
    return route.fulfill({ status: 404, json: { code: 'history_not_found', message: 'History not found' } });
  });
  return state;
}
