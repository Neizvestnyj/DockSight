import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import type { ApiClient } from './api';
import { Connection } from './Connection';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it('prefills the public API address and logs in through its same-origin proxy', async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValue(
      Response.json({ actor: 'operator', expires_at: '2026-12-01T12:00:00Z', csrf_token: 'c'.repeat(43) }),
    );
  vi.stubGlobal('fetch', fetcher);
  const connected = vi.fn<(client: ApiClient) => void>();
  render(<Connection close={() => {}} connect={connected} />);
  expect(screen.getByLabelText('API base URL')).toHaveValue(`${window.location.origin}/api/v1`);
  fireEvent.change(screen.getByLabelText('Bearer token'), { target: { value: 'test-only-connection-token' } });
  fireEvent.click(screen.getByRole('button', { name: 'Connect' }));
  await waitFor(() => expect(connected).toHaveBeenCalledOnce());
  expect(fetcher).toHaveBeenCalledWith(
    '/api/v1/auth/login',
    expect.objectContaining({ method: 'POST', credentials: 'same-origin' }),
  );
  expect(connected.mock.calls[0]?.[0].authentication).toBe('cookie');
  expect(screen.getByLabelText('Bearer token')).toHaveValue('');
});

for (const [code, status, message, hint] of [
  ['origin_not_allowed', 403, 'Origin is not allowed', 'DOCKSIGHT_BROWSER_ORIGIN'],
  ['insecure_browser_origin', 403, 'Browser login requires HTTPS', 'DOCKSIGHT_COOKIE_SECURE=false'],
  ['unauthorized', 401, 'Unauthorized', 'The API rejected the bearer token.'],
] as const) {
  it(`identifies ${code} without blaming a valid relative API address`, async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({ code, message }, { status })));
    const connected = vi.fn();
    render(<Connection close={() => {}} connect={connected} />);
    fireEvent.change(screen.getByLabelText('API base URL'), { target: { value: '/api/v1' } });
    fireEvent.change(screen.getByLabelText('Bearer token'), { target: { value: 'test-only-connection-token' } });
    fireEvent.click(screen.getByRole('button', { name: 'Connect' }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(hint);
    if (code === 'origin_not_allowed') expect(alert).toHaveTextContent(window.location.origin);
    expect(alert).not.toHaveTextContent('Check the API endpoint.');
    expect(alert).not.toHaveTextContent('test-only-connection-token');
    expect(connected).not.toHaveBeenCalled();
    expect(screen.getByLabelText('Bearer token')).toHaveValue('');
  });
}
