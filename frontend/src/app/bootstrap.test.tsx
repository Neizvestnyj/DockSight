import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import App from './App';
import { ApiClient } from '../infrastructure/api/api';
import { ApiError } from '../shared/contracts/errors';
import { Connection } from '../modules/session/ui/Connection';
import { connectApi } from './bootstrap/connectApi';
import { LocaleProvider } from './providers/LocaleProvider';
import { DemoClient, demoSystemStatus } from '../infrastructure/demo/demo';

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
        connectApi={connectApi}
        close={() => {}}
        connect={(client) => {
          authentication = (client as ApiClient).authentication;
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

it.each([
  ['available', 'ok'],
  ['unavailable', 'model_not_found'],
] as const)('uses exact model status %s for a saved draft when the catalog read fails', async (state, code) => {
  const id = crypto.randomUUID();
  const model = { provider: 'ollama', model: 'qwen3.5:9b' } as const;
  vi.spyOn(ApiClient.prototype, 'session').mockResolvedValue({
    actor: 'operator',
    expires_at: '2026-12-01T12:00:00Z',
    csrf_token: 'c'.repeat(43),
  });
  vi.spyOn(ApiClient.prototype, 'actorWorkspace').mockResolvedValue({
    revision: 1,
    last_investigation_id: id,
    host: 'local',
    model,
  });
  vi.spyOn(ApiClient.prototype, 'investigation').mockResolvedValue({
    id,
    host: 'local',
    title: '',
    created_at: '2026-11-04T12:00:00Z',
    updated_at: '2026-11-04T12:00:00Z',
    active_turn_id: null,
    turn_count: 0,
    workspace: { revision: 0, draft: 'Как жизнь?', target: null, selected_container: null, view: 'diagnostics' },
    turns: { items: [], next_cursor: null },
  });
  vi.spyOn(ApiClient.prototype, 'hosts').mockResolvedValue([{ id: 'local', name: 'Local Docker' }]);
  vi.spyOn(ApiClient.prototype, 'investigations').mockResolvedValue({ items: [], next_cursor: null });
  vi.spyOn(ApiClient.prototype, 'containers').mockResolvedValue([]);
  const catalog = vi.spyOn(ApiClient.prototype, 'modelProviders').mockRejectedValue(new TypeError('offline'));
  const healthy = demoSystemStatus('local');
  const status = vi.spyOn(ApiClient.prototype, 'systemStatus').mockResolvedValue({
    ...healthy,
    ...model,
    model_check: { ...healthy.model_check, state, code },
  });
  render(<App />);
  expect(await screen.findByRole('textbox')).toHaveValue('Как жизнь?');
  await waitFor(() => expect(catalog).toHaveBeenCalled());
  await waitFor(() => expect(status).toHaveBeenCalledWith('local', expect.any(AbortSignal), model));
  const investigate = screen.getByRole('button', { name: 'Investigate' });
  if (state === 'available') await waitFor(() => expect(investigate).toBeEnabled());
  else {
    await screen.findByText('The configured model is unavailable. You can still inspect Docker directly.');
    expect(investigate).toBeDisabled();
    fireEvent.focus(screen.getByRole('button', { name: 'Why diagnosis is unavailable' }));
    expect(screen.getByRole('tooltip', { hidden: true })).toHaveTextContent('The configured model is unavailable.');
  }
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
