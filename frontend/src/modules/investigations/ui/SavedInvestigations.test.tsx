import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { SavedInvestigations } from './SavedInvestigations';
import { LocaleProvider } from '../../../app/providers/LocaleProvider';
import { ApiClient } from '../../../infrastructure/api/api';

afterEach(cleanup);
it('names saved chats and confirms the exact archive before deletion', () => {
  const remove = vi.fn();
  render(
    <LocaleProvider>
      <SavedInvestigations
        items={[
          {
            id: 'chat',
            title: 'Worker failed',
            host: 'local',
            created_at: '2026-11-04T12:00:00Z',
            updated_at: '2026-11-04T12:00:00Z',
            turn_count: 1,
            active_turn_id: null,
          },
        ]}
        selected="chat"
        loading={false}
        error=""
        nextCursor={null}
        open={vi.fn()}
        older={vi.fn()}
        refresh={vi.fn()}
        remove={remove}
      />
    </LocaleProvider>,
  );
  fireEvent.click(screen.getByRole('button', { name: 'Delete saved chat: Worker failed' }));
  expect(remove).not.toHaveBeenCalled();
  expect(screen.getByRole('dialog')).toHaveTextContent('Worker failed');
  fireEvent.click(screen.getByRole('button', { name: 'Delete chat' }));
  expect(remove).toHaveBeenCalledWith('chat');
});

it('keeps chat search separate from recent history and opens the matched question', async () => {
  const id = '11111111-1111-4111-8111-111111111111';
  const turnId = '22222222-2222-4222-8222-222222222222';
  const open = vi.fn();
  const api = new ApiClient('/api/v1', '', async () =>
    Response.json({
      items: [
        {
          id,
          host: 'old-host',
          title: 'Previous incident',
          updated_at: '2026-11-04T12:00:00Z',
          match: { turn_id: turnId, excerpt: 'Check timeout during startup', start: 6, end: 13 },
        },
      ],
      next_cursor: null,
    }),
  );
  render(
    <SavedInvestigations
      items={[]}
      selected={id}
      loading={false}
      error=""
      nextCursor={null}
      open={open}
      older={vi.fn()}
      refresh={vi.fn()}
      remove={vi.fn()}
      searchHistory={api}
    />,
  );
  const trigger = screen.getByRole('button', { name: 'Search chats' });
  fireEvent.click(trigger);
  const field = screen.getByRole('searchbox');
  fireEvent.change(field, { target: { value: 'timeout' } });
  const match = await screen.findByRole('button', { name: /Previous incident.*timeout.*old-host/ });
  expect(match.querySelector('mark')).toHaveTextContent('timeout');
  expect(match).toHaveAttribute('aria-current', 'page');
  expect(screen.queryByText('No saved chats yet.')).toBeNull();
  fireEvent.click(match);
  expect(open).toHaveBeenCalledExactlyOnceWith(id, turnId);

  fireEvent.keyDown(field, { key: 'Escape' });
  expect(trigger).toHaveFocus();
  expect(screen.queryByRole('searchbox')).toBeNull();
  expect(screen.getByText('No saved chats yet.')).toBeVisible();

  fireEvent.click(trigger);
  const refresh = screen.getByRole('button', { name: 'Refresh saved chats' });
  refresh.focus();
  fireEvent.click(refresh);
  expect(screen.queryByRole('searchbox')).toBeNull();
  expect(refresh).toHaveFocus();
});
