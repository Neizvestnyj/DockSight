import '@testing-library/jest-dom/vitest';
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import App from './App';
import { ApiClient, ApiError } from './api';
import { DemoClient } from './demo';
import { useSystemStatus } from './useSystemStatus';

const check = {
  state: 'available' as const,
  code: 'ok' as const,
  message: 'Availability check succeeded.',
  checked_at: '2026-10-27T12:00:00Z',
};
const healthy = {
  schema_version: 1 as const,
  host: 'demo-eu',
  provider: 'ollama' as const,
  model: 'qwen3.5:9b',
  docker: check,
  provider_check: check,
  model_check: check,
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('system availability', () => {
  it('authenticates status requests and preserves the HTTP status of rejected credentials', async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json(healthy));
    const api = new ApiClient('/api/v1', 'test-token', fetcher);
    const signal = new AbortController().signal;
    expect(await api.systemStatus('demo-eu', signal)).toEqual(healthy);
    expect(fetcher.mock.calls[0]![0]).toBe('/api/v1/system/status?host=demo-eu');
    expect(new Headers(fetcher.mock.calls[0]![1].headers).get('Authorization')).toBe('Bearer test-token');
    fetcher.mockResolvedValue(
      Response.json({ code: 'unauthorized', message: 'Authentication required' }, { status: 401 }),
    );
    await expect(api.systemStatus(null, signal)).rejects.toMatchObject({ httpStatus: 401, code: 'unauthorized' });
  });

  it('keeps Demo checks manual and retains old timestamps while refreshing', async () => {
    const client = new DemoClient();
    let finish: (value: typeof healthy) => void = () => {};
    client.systemStatus = vi
      .fn()
      .mockResolvedValueOnce(healthy)
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finish = resolve;
          }),
      );
    const { result } = renderHook(() => useSystemStatus(client, 'demo-eu'));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(client.systemStatus).toHaveBeenCalledTimes(1);
    act(() => result.current.refresh());
    expect(result.current.loading).toBe(true);
    expect(result.current.data?.docker.checked_at).toBe(check.checked_at);
    await act(async () => finish(healthy));
    expect(client.systemStatus).toHaveBeenCalledTimes(2);
  });

  it('distinguishes rejected credentials from a network failure and retains previous dependency results', async () => {
    const client = new DemoClient();
    client.systemStatus = vi
      .fn()
      .mockResolvedValueOnce(healthy)
      .mockRejectedValueOnce(new ApiError('private upstream', 'unauthorized', undefined, 'server', 401))
      .mockRejectedValueOnce(new TypeError('private endpoint'));
    const { result } = renderHook(() => useSystemStatus(client, 'demo-eu'));
    await waitFor(() => expect(result.current.loading).toBe(false));
    act(() => result.current.refresh());
    await waitFor(() => expect(result.current.api.reason).toBe('The API rejected the bearer token.'));
    expect(result.current.data?.docker.checked_at).toBe(check.checked_at);
    act(() => result.current.refresh());
    await waitFor(() =>
      expect(result.current.api.reason).toBe('No connection to the API. Check the endpoint and network.'),
    );
  });

  it('cancels old host checks and ignores late responses', async () => {
    const client = new DemoClient();
    let finish: (value: typeof healthy) => void = () => {};
    let signal: AbortSignal | undefined;
    client.systemStatus = vi
      .fn()
      .mockImplementationOnce((_host, pendingSignal) => {
        signal = pendingSignal;
        return new Promise((resolve) => {
          finish = resolve;
        });
      })
      .mockResolvedValueOnce({ ...healthy, host: 'demo-empty' });
    const { result, rerender } = renderHook(({ host }) => useSystemStatus(client, host), {
      initialProps: { host: 'demo-eu' },
    });
    rerender({ host: 'demo-empty' });
    await waitFor(() => expect(result.current.data?.host).toBe('demo-empty'));
    await act(async () => finish(healthy));
    expect(signal?.aborted).toBe(true);
    expect(result.current.data?.host).toBe('demo-empty');
  });

  it('keeps direct Docker views available when model metadata fails and allows unchecked models', async () => {
    const status = vi
      .spyOn(DemoClient.prototype, 'systemStatus')
      .mockResolvedValue({ ...healthy, model_check: { ...check, state: 'unavailable', code: 'model_not_found' } });
    const diagnose = vi.spyOn(DemoClient.prototype, 'diagnose');
    render(<App />);
    fireEvent.click(await screen.findByTitle('payments-api'));
    const facts = screen.getByRole('region', { name: 'Container facts' });
    expect(await within(facts).findByText('APP_ENV')).toBeInTheDocument();
    expect(within(facts).getByRole('button', { name: 'Diagnose' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: /^System status/ }));
    const panel = screen.getByRole('dialog', { name: 'System status' });
    expect(panel).toHaveTextContent('qwen3.5:9b');
    expect(panel).toHaveTextContent('Tools and structured output have not been tested.');
    status.mockResolvedValue({ ...healthy, model_check: { ...check, state: 'not_checked', code: 'unsupported' } });
    fireEvent.click(within(panel).getByRole('button', { name: 'Check again' }));
    await waitFor(() => expect(within(panel).getByRole('button', { name: 'Check again' })).toBeEnabled());
    fireEvent.click(within(panel).getByRole('button', { name: 'Close dialog' }));
    expect(within(facts).getByRole('button', { name: 'Diagnose' })).toBeEnabled();
    expect(diagnose).not.toHaveBeenCalled();
  });
});
