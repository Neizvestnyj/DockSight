import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import App from './App';
import { ApiClient, ApiError } from './api';
import { Connection } from './Connection';
import { LocaleProvider } from './LocaleProvider';
import { DemoClient, demoSystemStatus } from './demo';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
it('restores a cookie-owned archive and keeps a removed host readable without substituting the sole host', async () => {
  const id = crypto.randomUUID();
  vi.spyOn(ApiClient.prototype, 'session').mockResolvedValue({
    actor: 'operator',
    expires_at: '2026-12-01T12:00:00Z',
    csrf_token: 'c'.repeat(43),
  });
  vi.spyOn(ApiClient.prototype, 'actorWorkspace').mockResolvedValue({
    revision: 1,
    last_investigation_id: id,
    host: 'removed',
    model: null,
  });
  vi.spyOn(ApiClient.prototype, 'investigation').mockResolvedValue({
    id,
    host: 'removed',
    title: 'Archived question',
    created_at: '2026-11-04T12:00:00Z',
    updated_at: '2026-11-04T12:00:00Z',
    active_turn_id: null,
    turn_count: 0,
    workspace: {
      revision: 0,
      draft: 'Acknowledged archive draft',
      target: null,
      selected_container: null,
      view: 'diagnostics',
    },
    turns: { items: [], next_cursor: null },
  });
  vi.spyOn(ApiClient.prototype, 'hosts').mockResolvedValue([{ id: 'other', name: 'Other configured host' }]);
  vi.spyOn(ApiClient.prototype, 'investigations').mockResolvedValue({ items: [], next_cursor: null });
  vi.spyOn(ApiClient.prototype, 'containers').mockResolvedValue([]);
  vi.spyOn(ApiClient.prototype, 'systemStatus').mockResolvedValue(demoSystemStatus('removed'));
  const created = vi.spyOn(ApiClient.prototype, 'createInvestigation');
  const demo = vi.spyOn(DemoClient.prototype, 'hosts');
  render(<App />);
  expect(await screen.findByRole('textbox')).toHaveValue('Acknowledged archive draft');
  expect(
    screen.getByText('Choose a configured host to continue. Saved evidence remains readable.'),
  ).toBeInTheDocument();
  expect(document.querySelector('.composer-foot')).toHaveTextContent('removed');
  expect(screen.getByRole('button', { name: 'Investigate' })).toBeDisabled();
  expect(created).not.toHaveBeenCalled();
  expect(demo).not.toHaveBeenCalled();
});

it('clears the raw login input after exchanging it for cookie authority', async () => {
  const login = vi
    .spyOn(ApiClient.prototype, 'login')
    .mockResolvedValue({ actor: 'operator', expires_at: '2026-12-01T12:00:00Z', csrf_token: 'c'.repeat(43) });
  let authentication = '';
  render(
    <LocaleProvider>
      <Connection
        close={() => {}}
        connect={(client) => {
          authentication = client.authentication;
        }}
      />
    </LocaleProvider>,
  );
  fireEvent.change(screen.getByLabelText('Bearer token'), { target: { value: 'one-time-private-token' } });
  fireEvent.click(screen.getByRole('button', { name: 'Connect' }));
  await waitFor(() => expect(screen.getByLabelText('Bearer token')).toHaveValue(''));
  expect(login).toHaveBeenCalledWith('one-time-private-token');
  expect(authentication).toBe('cookie');
  expect(Object.keys(sessionStorage)).toEqual([]);
  expect(Object.keys(localStorage).every((key) => key === 'docksight.locale')).toBe(true);
});
it('offers signed-out controls after 401 and enters Demo only explicitly', async () => {
  vi.spyOn(ApiClient.prototype, 'session').mockRejectedValue(
    new ApiError('Sign in', 'unauthorized', undefined, 'server', 401),
  );
  render(<App />);
  expect(await screen.findByText('Sign in to DockSight')).toBeInTheDocument();
  expect(
    screen.queryByText('Example data from a fictional host. Connect an API to diagnose your Docker.'),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Explore Demo' }));
  expect(
    await screen.findByText('Example data from a fictional host. Connect an API to diagnose your Docker.'),
  ).toBeInTheDocument();
});
it('offers a retry after bootstrap network failure without fictional recovery', async () => {
  vi.spyOn(ApiClient.prototype, 'session').mockRejectedValue(new TypeError('offline'));
  render(<App />);
  expect(await screen.findByText('Could not restore your session.')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Retry connection' })).toBeInTheDocument();
  expect(screen.queryByLabelText('Demo scenario')).not.toBeInTheDocument();
});
