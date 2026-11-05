import { chooseOption } from '../test-utils/select';
import '@testing-library/jest-dom/vitest';
import { act, cleanup, fireEvent, renderHook, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderDemoApp } from '../test-utils/demo';
import { ApiClient } from './api';
import { DemoClient, demoSystemStatus } from './demo';
import { useModelCatalog } from './useModelCatalog';
import { useSystemStatus } from './useSystemStatus';
import { useInvestigation } from './useInvestigation';
import type { ModelCatalog, ModelSelection } from './model-contracts';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('model selection', async () => {
  it('loads catalogs only when opened and preserves the draft, evidence and prepared actions when switching', async () => {
    const providers = vi.spyOn(DemoClient.prototype, 'modelProviders');
    const catalogs = vi.spyOn(DemoClient.prototype, 'models');
    await renderDemoApp();
    expect(providers).not.toHaveBeenCalled();
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Keep this follow-up' } });
    fireEvent.click(screen.getByRole('button', { name: 'Review stop' }));
    const action = screen.getByRole('dialog').querySelector('.confirmation-facts code:last-child')?.textContent;
    fireEvent.click(screen.getByRole('button', { name: 'Close dialog' }));
    fireEvent.click(screen.getByRole('button', { name: /Choose model/ }));
    const picker = screen.getByRole('dialog', { name: 'Choose model' });
    await waitFor(() => expect(catalogs).toHaveBeenCalledTimes(1));
    chooseOption(within(picker).getByRole('combobox', { name: 'Provider' }), 'gemini');
    fireEvent.click(await within(picker).findByRole('button', { name: /gemini-demo/ }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Choose model/ })).toHaveTextContent('gemini-demo');
    expect(screen.getByRole('textbox')).toHaveValue('Keep this follow-up');
    expect(screen.getByText('Diagnostic conclusion')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Review stop' }));
    expect(screen.getByRole('dialog').querySelector('.confirmation-facts code:last-child')?.textContent).toBe(action);
    fireEvent.click(screen.getByRole('button', { name: 'Close dialog' }));
    fireEvent.click(screen.getByRole('button', { name: /Choose model/ }));
    expect(await within(screen.getByRole('dialog')).findByRole('button', { name: /gemini-demo/ })).toBeVisible();
    expect(catalogs).toHaveBeenCalledTimes(2);
  });

  it('sends selection only on subsequent turns and retains it when changing hosts', async () => {
    const diagnose = vi.spyOn(DemoClient.prototype, 'diagnose').mockResolvedValue();
    await renderDemoApp();
    fireEvent.click(screen.getByRole('button', { name: /Choose model/ }));
    const picker = screen.getByRole('dialog');
    chooseOption(await within(picker).findByRole('combobox', { name: 'Provider' }), 'gemini');
    fireEvent.click(await within(picker).findByRole('button', { name: /gemini-demo/ }));
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Inspect payments-api' } });
    await act(async () => fireEvent.click(screen.getByRole('button', { name: /^Investigate$/ })));
    expect(diagnose.mock.calls[0]?.[0].model_selection).toEqual({ provider: 'gemini', model: 'gemini-demo' });
    chooseOption(screen.getByRole('combobox', { name: 'Configured host' }), 'demo-empty');
    expect(screen.getByRole('button', { name: /Choose model/ })).toHaveTextContent('gemini-demo');
  });

  it('authenticates and validates provider catalogs and selected status identity', async () => {
    const fetcher = vi.fn().mockResolvedValue(
      Response.json({
        schema_version: 1,
        provider: 'ollama',
        models: [{ id: 'qwen3.5:9b' }],
        state: 'ready',
        code: 'ok',
        checked_at: '2026-10-30T12:00:00Z',
        refreshing: false,
      }),
    );
    const client = new ApiClient('/api/v1', 'test-token', fetcher);
    const signal = new AbortController().signal;
    await client.models('ollama', signal, true);
    expect(fetcher.mock.calls[0]?.[0]).toBe('/api/v1/model-providers/ollama/models?refresh=true');
    expect(new Headers(fetcher.mock.calls[0]?.[1].headers).get('Authorization')).toBe('Bearer test-token');
    await expect(client.models('gemini', signal)).rejects.toThrow();
    fetcher.mockResolvedValue(Response.json(demoSystemStatus('demo-eu')));
    await expect(
      client.systemStatus('demo-eu', signal, { provider: 'gemini', model: 'gemini-demo' }),
    ).rejects.toThrow();
    expect(fetcher.mock.calls.at(-1)?.[0]).toBe('/api/v1/system/status?host=demo-eu&provider=gemini&model=gemini-demo');
  });

  it('coalesces model reads, reuses fresh rows and keeps them visible when refreshing fails', async () => {
    const client = new DemoClient();
    const data = await client.models('ollama', new AbortController().signal);
    let finish: (catalog: ModelCatalog) => void = () => {};
    client.models = vi.fn().mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const { result } = renderHook(() => useModelCatalog(client));
    let first: Promise<void> | undefined;
    act(() => {
      first = result.current.loadCatalog('ollama');
      expect(result.current.loadCatalog('ollama')).toBe(first);
    });
    await act(async () => {
      finish(data);
      await first;
    });
    await act(async () => {
      await result.current.loadCatalog('ollama');
    });
    expect(client.models).toHaveBeenCalledTimes(1);
    vi.mocked(client.models).mockRejectedValueOnce(new TypeError('private connection failure'));
    await act(async () => {
      await result.current.loadCatalog('ollama', true);
    });
    expect(result.current.catalogs.ollama?.data?.models).toEqual(data.models);
    expect(result.current.catalogs.ollama?.error).toBe(true);
  });

  it('does not reset the investigation session when the selected provider changes', async () => {
    const client = new DemoClient();
    const session = crypto.randomUUID();
    const diagnose = vi.spyOn(client, 'diagnose').mockImplementation(async (_input, receive) => {
      const envelope = { schema_version: 1 as const, request_id: 'request', turn_id: crypto.randomUUID() };
      receive({ ...envelope, type: 'turn.started', session_id: session });
      receive({ ...envelope, type: 'turn.completed' });
    });
    const { result, rerender } = renderHook(
      ({ selection }: { selection?: ModelSelection }) => useInvestigation(client, 'demo-eu', undefined, selection),
      { initialProps: { selection: undefined as ModelSelection | undefined } },
    );
    await act(async () => {
      await result.current.run('First question');
    });
    expect(diagnose.mock.calls[0]?.[0]).not.toHaveProperty('model_selection');
    rerender({ selection: { provider: 'gemini', model: 'gemini-demo' } });
    await act(async () => {
      await result.current.run('Follow-up');
    });
    expect(diagnose.mock.calls[1]?.[0]).toMatchObject({
      session_id: session,
      model_selection: { provider: 'gemini', model: 'gemini-demo' },
    });
    expect(result.current.turns).toHaveLength(2);
  });

  it('cancels a default status read when selection changes and ignores its late response', async () => {
    const client = new DemoClient();
    const data = demoSystemStatus('demo-eu');
    let finish: (value: typeof data) => void = () => {};
    let oldSignal: AbortSignal | undefined;
    client.systemStatus = vi
      .fn()
      .mockImplementationOnce((_host, signal: AbortSignal) => {
        oldSignal = signal;
        return new Promise((resolve) => {
          finish = resolve;
        });
      })
      .mockResolvedValueOnce({ ...data, provider: 'gemini', model: 'gemini-demo' });
    const { result, rerender } = renderHook(
      ({ selection }: { selection?: ModelSelection }) => useSystemStatus(client, 'demo-eu', true, false, selection),
      { initialProps: { selection: undefined as ModelSelection | undefined } },
    );
    rerender({ selection: { provider: 'gemini', model: 'gemini-demo' } });
    await waitFor(() => expect(result.current.data?.provider).toBe('gemini'));
    await act(async () => {
      finish(data);
    });
    expect(oldSignal?.aborted).toBe(true);
    expect(result.current.data?.model).toBe('gemini-demo');
    expect(result.current.blockedReason).toBeUndefined();
  });
});
