import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from './api';
import { DemoClient, demoSystemStatus } from './demo';
import { useSystemStatus } from './useSystemStatus';

beforeEach(() => {
  vi.useFakeTimers();
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
  vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(true);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

/** Advance time while settling check results and their React updates. */
async function advance(milliseconds: number) {
  await act(async () => vi.advanceTimersByTimeAsync(milliseconds));
}

describe('automatic system checks', () => {
  it('checks once a minute and releases diagnosis blocking after a failed dependency recovers', async () => {
    const client = new DemoClient();
    const healthy = demoSystemStatus('local');
    const check = vi.spyOn(client, 'systemStatus').mockResolvedValue(healthy);
    const { result } = renderHook(() => useSystemStatus(client, 'local', true, true));
    await advance(0);
    expect(result.current.blockedReason).toBeUndefined();
    check.mockResolvedValue({
      ...healthy,
      docker: { ...healthy.docker, state: 'unavailable', code: 'runtime_unavailable' },
    });
    await advance(59_999);
    expect(check).toHaveBeenCalledOnce();
    await advance(1);
    expect(result.current.blockedReason).toMatch(/Docker is unavailable/);
    check.mockResolvedValue(healthy);
    await advance(120_000);
    expect(result.current.blockedReason).toBeUndefined();
    expect(check).toHaveBeenCalledTimes(3);
    await advance(60_000);
    expect(check).toHaveBeenCalledTimes(4);
  });

  it('retains dependency timestamps after a network failure and backs off to five minutes', async () => {
    const client = new DemoClient();
    const healthy = demoSystemStatus('local');
    const check = vi
      .spyOn(client, 'systemStatus')
      .mockResolvedValueOnce(healthy)
      .mockRejectedValue(new TypeError('offline'));
    const { result } = renderHook(() => useSystemStatus(client, 'local', true, true));
    await advance(0);
    await advance(60_000);
    expect(result.current.api.state).toBe('unavailable');
    expect(result.current.data?.docker.checked_at).toBe(healthy.docker.checked_at);
    for (const delay of [120_000, 240_000, 300_000, 300_000]) {
      const calls = check.mock.calls.length;
      await advance(delay - 1);
      expect(check).toHaveBeenCalledTimes(calls);
      await advance(1);
      expect(check).toHaveBeenCalledTimes(calls + 1);
    }
    check.mockResolvedValue(healthy);
    await advance(300_000);
    expect(result.current.api.state).toBe('available');
    await advance(60_000);
    expect(result.current.blockedReason).toBeUndefined();
  });

  it.each([401, 403])('stops automatic checks after HTTP %s until a successful manual retry', async (httpStatus) => {
    const client = new DemoClient();
    const check = vi
      .spyOn(client, 'systemStatus')
      .mockRejectedValue(new ApiError('Denied', 'unauthorized', undefined, 'server', httpStatus));
    const { result } = renderHook(() => useSystemStatus(client, 'local', true, true));
    await advance(600_000);
    await act(async () => window.dispatchEvent(new Event('focus')));
    expect(check).toHaveBeenCalledOnce();
    await act(async () => result.current.refreshIfStale());
    expect(check).toHaveBeenCalledOnce();
    check.mockRejectedValue(new TypeError('offline'));
    await act(async () => result.current.refresh());
    await advance(600_000);
    expect(check).toHaveBeenCalledTimes(2);
    check.mockResolvedValue(demoSystemStatus('local'));
    await act(async () => result.current.refresh());
    await advance(60_000);
    expect(check).toHaveBeenCalledTimes(4);
  });

  it('checks stale results on foreground and panel access while leaving fresh results scheduled', async () => {
    const client = new DemoClient();
    const check = vi.spyOn(client, 'systemStatus').mockResolvedValue(demoSystemStatus('local'));
    const visibility = vi.spyOn(document, 'visibilityState', 'get');
    const online = vi.spyOn(navigator, 'onLine', 'get');
    const { result } = renderHook(() => useSystemStatus(client, 'local', true, true));
    await advance(0);
    await advance(10_000);
    await act(async () => window.dispatchEvent(new Event('focus')));
    await act(async () => result.current.refreshIfStale());
    expect(check).toHaveBeenCalledOnce();
    await advance(50_000);
    expect(check).toHaveBeenCalledTimes(2);
    visibility.mockReturnValue('hidden');
    act(() => document.dispatchEvent(new Event('visibilitychange')));
    await advance(60_000);
    expect(check).toHaveBeenCalledTimes(2);
    visibility.mockReturnValue('visible');
    await act(async () => document.dispatchEvent(new Event('visibilitychange')));
    expect(check).toHaveBeenCalledTimes(3);
    await advance(30_000);
    await act(async () => result.current.refreshIfStale());
    expect(check).toHaveBeenCalledTimes(4);
    online.mockReturnValue(false);
    act(() => window.dispatchEvent(new Event('offline')));
    await advance(60_000);
    expect(check).toHaveBeenCalledTimes(4);
    online.mockReturnValue(true);
    await act(async () => window.dispatchEvent(new Event('online')));
    expect(check).toHaveBeenCalledTimes(5);
  });

  it('resumes automatic recovery after authorization succeeds even when Docker is still unavailable', async () => {
    const client = new DemoClient();
    const healthy = demoSystemStatus('local');
    const check = vi
      .spyOn(client, 'systemStatus')
      .mockRejectedValue(new ApiError('Denied', 'unauthorized', undefined, 'server', 401));
    const { result } = renderHook(() => useSystemStatus(client, 'local', true, true));
    await advance(0);
    check.mockResolvedValue({
      ...healthy,
      docker: { ...healthy.docker, state: 'unavailable', code: 'runtime_unavailable' },
    });
    await act(async () => result.current.refresh());
    expect(result.current.stopped).toBe(false);
    check.mockResolvedValue(healthy);
    await advance(120_000);
    expect(result.current.blockedReason).toBeUndefined();
    expect(check).toHaveBeenCalledTimes(3);
  });

  it('leaves Demo manual and does not run checks before host discovery is enabled', async () => {
    const client = new DemoClient();
    const check = vi.spyOn(client, 'systemStatus').mockResolvedValue(demoSystemStatus('local'));
    const { result, rerender } = renderHook(({ enabled }) => useSystemStatus(client, 'local', enabled, false), {
      initialProps: { enabled: false },
    });
    await advance(60_000);
    expect(check).not.toHaveBeenCalled();
    rerender({ enabled: true });
    await advance(600_000);
    await act(async () => result.current.refreshIfStale());
    expect(check).toHaveBeenCalledOnce();
    await act(async () => result.current.refresh());
    expect(check).toHaveBeenCalledTimes(2);
  });
});
