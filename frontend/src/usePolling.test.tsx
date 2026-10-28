import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { usePolling, type PollResult } from './usePolling';

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

/** Advance the polling clock and settle asynchronous reads inside React. */
async function advance(milliseconds: number) {
  await act(async () => vi.advanceTimersByTimeAsync(milliseconds));
}

describe('runtime polling', () => {
  it('waits ten seconds after settlement and prevents overlapping automatic reads', async () => {
    let finish: (result: PollResult) => void = () => {};
    const read = vi.fn(
      () =>
        new Promise<PollResult>((resolve) => {
          finish = resolve;
        }),
    );
    renderHook(() => usePolling(read, true));
    expect(read).toHaveBeenCalledOnce();
    await advance(30_000);
    expect(read).toHaveBeenCalledOnce();
    await act(async () => finish('success'));
    await advance(9999);
    expect(read).toHaveBeenCalledOnce();
    await advance(1);
    expect(read).toHaveBeenCalledTimes(2);
    expect(read.mock.calls[1]).toEqual([expect.any(AbortSignal), 'automatic']);
  });

  it('backs off failures to a minute and restores the normal interval after recovery', async () => {
    const read = vi.fn<() => Promise<PollResult>>().mockResolvedValue('retry');
    renderHook(() => usePolling(read, true));
    await advance(0);
    for (const delay of [20_000, 40_000, 60_000, 60_000]) {
      const calls = read.mock.calls.length;
      await advance(delay - 1);
      expect(read).toHaveBeenCalledTimes(calls);
      await advance(1);
      expect(read).toHaveBeenCalledTimes(calls + 1);
    }
    read.mockResolvedValue('success');
    await advance(60_000);
    const calls = read.mock.calls.length;
    await advance(10_000);
    expect(read).toHaveBeenCalledTimes(calls + 1);
  });

  it('pauses in a hidden or offline page and rereads immediately on return', async () => {
    const visibility = vi.spyOn(document, 'visibilityState', 'get');
    const online = vi.spyOn(navigator, 'onLine', 'get');
    const read = vi.fn<() => Promise<PollResult>>().mockResolvedValue('success');
    renderHook(() => usePolling(read, true));
    await advance(0);
    visibility.mockReturnValue('hidden');
    act(() => document.dispatchEvent(new Event('visibilitychange')));
    await advance(60_000);
    expect(read).toHaveBeenCalledOnce();
    visibility.mockReturnValue('visible');
    await act(async () => document.dispatchEvent(new Event('visibilitychange')));
    expect(read).toHaveBeenCalledTimes(2);
    online.mockReturnValue(false);
    act(() => window.dispatchEvent(new Event('offline')));
    await advance(60_000);
    expect(read).toHaveBeenCalledTimes(2);
    online.mockReturnValue(true);
    await act(async () => window.dispatchEvent(new Event('online')));
    expect(read).toHaveBeenCalledTimes(3);
  });

  it('does not poll or react to focus in demo mode, but permits manual refresh', async () => {
    const read = vi.fn<() => Promise<PollResult>>().mockResolvedValue('success');
    const { result } = renderHook(() => usePolling(read, false));
    await advance(60_000);
    await act(async () => window.dispatchEvent(new Event('focus')));
    expect(read).toHaveBeenCalledOnce();
    await act(async () => result.current());
    expect(read).toHaveBeenLastCalledWith(expect.any(AbortSignal), 'manual');
  });

  it('aborts old reads and cancels their timers when the resource changes or unmounts', async () => {
    const oldRead = vi.fn<(signal: AbortSignal) => Promise<PollResult>>(() => new Promise(() => {}));
    const newRead = vi.fn<() => Promise<PollResult>>().mockResolvedValue('success');
    const { rerender, unmount } = renderHook(({ read }) => usePolling(read, true), {
      initialProps: { read: oldRead },
    });
    const signal = oldRead.mock.calls[0]![0];
    rerender({ read: newRead });
    expect(signal.aborted).toBe(true);
    await advance(0);
    unmount();
    await advance(60_000);
    expect(newRead).toHaveBeenCalledOnce();
  });

  it('stops automatic reads after a missing resource until an explicit manual retry', async () => {
    const read = vi.fn<() => Promise<PollResult>>().mockResolvedValue('stop');
    const { result } = renderHook(() => usePolling(read, true));
    await advance(60_000);
    await act(async () => window.dispatchEvent(new Event('focus')));
    expect(read).toHaveBeenCalledOnce();
    read.mockResolvedValue('retry');
    await act(async () => result.current());
    await advance(60_000);
    expect(read).toHaveBeenCalledTimes(2);
    read.mockResolvedValue('success');
    await act(async () => result.current());
    await advance(10_000);
    expect(read).toHaveBeenCalledTimes(4);
  });

  it('keeps an inactive container view idle and reads when it becomes active', async () => {
    const read = vi.fn<() => Promise<PollResult>>().mockResolvedValue('success');
    const { rerender } = renderHook(({ active }) => usePolling(read, true, active), {
      initialProps: { active: false },
    });
    await advance(60_000);
    expect(read).not.toHaveBeenCalled();
    rerender({ active: true });
    await advance(0);
    expect(read).toHaveBeenCalledOnce();
    rerender({ active: false });
    await advance(60_000);
    expect(read).toHaveBeenCalledOnce();
  });
});
