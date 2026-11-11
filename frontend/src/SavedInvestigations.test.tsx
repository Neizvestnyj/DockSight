import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { SavedInvestigations } from './SavedInvestigations';
import { LocaleProvider } from './LocaleProvider';

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
