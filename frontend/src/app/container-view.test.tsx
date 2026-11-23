import { chooseOption } from '../../test-utils/select';
import '@testing-library/jest-dom/vitest';
import { act, cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderDemoApp } from '../../test-utils/demo';
import { DemoClient, demoAnswer, demoContainer } from '../infrastructure/demo/demo';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('read-only container viewing', async () => {
  it('opens Docker facts without a model request and preserves historical cards and drafts', async () => {
    const diagnose = vi.spyOn(DemoClient.prototype, 'diagnose');
    const scenario = vi.spyOn(DemoClient.prototype, 'setScenario');
    await renderDemoApp({ example: true });
    await screen.findByTitle('payments-api');
    const originalTime = screen.getByRole('group', { name: 'Container status' }).querySelector('time')!.dateTime;
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Keep this follow-up' } });
    fireEvent.click(screen.getByTitle('payments-api'));
    const facts = await screen.findByRole('region', { name: 'Container facts' });
    expect(await within(facts).findByText('APP_ENV')).toBeInTheDocument();
    expect(within(facts).getByText('Starting application bootstrap')).toBeInTheDocument();
    expect(within(facts).queryByRole('button', { name: /Review (stop|restart)/ })).not.toBeInTheDocument();
    fireEvent.click(within(facts).getByRole('button', { name: 'Refresh data' }));
    await waitFor(() => expect(within(facts).getByRole('button', { name: 'Refresh data' })).toBeEnabled());
    expect(diagnose).not.toHaveBeenCalled();
    expect(scenario).not.toHaveBeenCalled();
    fireEvent.click(within(facts).getByRole('button', { name: 'Back to investigation' }));
    expect(screen.getByRole('textbox')).toHaveValue('Keep this follow-up');
    expect(screen.getByRole('group', { name: 'Container status' }).querySelector('time')!.dateTime).toBe(originalTime);
    expect(screen.getByRole('button', { name: 'Review stop' })).toBeInTheDocument();
  });

  it('retains successful observations when logs fail and retries only on manual refresh', async () => {
    const logs = vi.spyOn(DemoClient.prototype, 'logs').mockRejectedValue(new Error('Logs unavailable'));
    await renderDemoApp();
    fireEvent.click(await screen.findByTitle('payments-api'));
    const facts = await screen.findByRole('region', { name: 'Container facts' });
    expect(await within(facts).findByText('APP_ENV')).toBeInTheDocument();
    expect(await within(facts).findByRole('alert')).toHaveTextContent('Could not read container logs.');
    expect(logs).toHaveBeenCalledTimes(1);
    logs.mockResolvedValue({
      entries: [{ message: '<img src=x onerror=alert(1)>', timestamp: null }],
      truncated: true,
    });
    fireEvent.click(within(facts).getByRole('button', { name: 'Retry data' }));
    expect(await within(facts).findByText('<img src=x onerror=alert(1)>')).toBeInTheDocument();
    expect(within(facts).getByText('Truncated · partial evidence')).toBeInTheDocument();
    expect(facts.querySelector('.logs img')).toBeNull();
    expect(logs).toHaveBeenCalledTimes(2);
  });

  it('ignores a late container response after selecting another container', async () => {
    let finish: (value: ReturnType<typeof demoContainer>) => void = () => {};
    vi.spyOn(DemoClient.prototype, 'container')
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finish = resolve;
          }),
      )
      .mockResolvedValueOnce(demoContainer(1, 'demo-eu', '2026-10-27T12:00:00Z'));
    await renderDemoApp({ example: true });
    fireEvent.click(await screen.findByTitle('payments-api'));
    const continueChat = screen.getByRole('button', { name: 'Continue in current chat' });
    expect(continueChat).toHaveAttribute('aria-disabled', 'true');
    expect(continueChat).toHaveAccessibleDescription('Refreshing container data…');
    fireEvent.focus(continueChat);
    expect(screen.getByRole('tooltip', { hidden: true })).toHaveTextContent('Refreshing container data…');
    fireEvent.click(screen.getByTitle('report-worker'));
    const facts = screen.getByRole('region', { name: 'Container facts' });
    expect(await within(facts).findByText('137')).toBeInTheDocument();
    await act(async () => finish(demoContainer(0, 'demo-eu', '2026-10-27T12:00:01Z')));
    expect(within(facts).getByRole('heading', { name: 'report-worker' })).toBeInTheDocument();
    expect(within(facts).getByText('137')).toBeInTheDocument();
  });

  it('starts diagnosis only on explicit request for the selected exact container', async () => {
    const session = crypto.randomUUID();
    const diagnose = vi.spyOn(DemoClient.prototype, 'diagnose').mockImplementation(async (input, receive) => {
      const envelope = { schema_version: 1 as const, request_id: 'r', turn_id: 't' };
      receive({ ...envelope, type: 'turn.started', session_id: input.session_id ?? session });
      receive({ ...envelope, type: 'answer.ready', answer: demoAnswer('oom', input.host) });
      receive({ ...envelope, type: 'turn.completed' });
    });
    await renderDemoApp({ example: true });
    fireEvent.click(await screen.findByTitle('report-worker'));
    const button = screen.getByRole('button', { name: 'Diagnose in a new chat' });
    await waitFor(() => expect(button).toBeEnabled());
    expect(diagnose).not.toHaveBeenCalled();
    fireEvent.click(button);
    await screen.findByRole('heading', { name: /Investigate report-worker/ });
    expect(diagnose).toHaveBeenCalledOnce();
    expect(diagnose.mock.calls[0]?.[0]).toEqual({
      host: 'demo-eu',
      container_id: '2'.repeat(64),
      query: `Investigate report-worker (${'2'.repeat(64)}). What happened, and what evidence supports it?`,
    });
    const archived = screen.getByRole('region', { name: 'Demo chats' });
    fireEvent.click(within(archived).getByRole('button', { name: 'Why does payments-api keep restarting?' }));
    expect(screen.getByRole('heading', { name: 'Why does payments-api keep restarting?' })).toBeInTheDocument();
    expect.soft(screen.getByRole('combobox', { name: 'Demo scenario' })).toHaveTextContent('Crash loop');
    expect(diagnose).toHaveBeenCalledOnce();
    fireEvent.click(within(archived).getByRole('button', { name: /Investigate report-worker/ }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Continue the investigation' }), {
      target: { value: 'Check the exit code again.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Investigate' }));
    await screen.findByRole('heading', { name: 'Check the exit code again.' });
    expect(diagnose.mock.calls[1]?.[0]).toMatchObject({ session_id: session, container_id: '2'.repeat(64) });
  });

  it('retains the last data and its timestamp during refresh and after a failed refresh', async () => {
    let fail: (error: Error) => void = () => {};
    const logs = vi
      .spyOn(DemoClient.prototype, 'logs')
      .mockResolvedValueOnce({
        entries: [{ message: 'Last successful log', timestamp: null }],
        truncated: false,
      })
      .mockImplementationOnce(
        () =>
          new Promise((_resolve, reject) => {
            fail = reject;
          }),
      );
    await renderDemoApp();
    fireEvent.click(await screen.findByTitle('payments-api'));
    const facts = screen.getByRole('region', { name: 'Container facts' });
    const panel = within(facts).getByRole('region', { name: 'Container logs' });
    await waitFor(() => expect(within(facts).getByRole('button', { name: 'Refresh data' })).toBeEnabled());
    const received = panel.querySelector('footer time')!.getAttribute('datetime');
    fireEvent.click(within(facts).getByRole('button', { name: 'Refresh data' }));
    expect(panel).toHaveAttribute('aria-busy', 'true');
    expect(panel).toHaveTextContent('Last successful log');
    await act(async () => fail(new Error('Connection lost')));
    expect(await within(panel).findByRole('alert')).toHaveTextContent('Could not read container logs.');
    expect(panel).toHaveTextContent('Showing the last successful observation.');
    expect(panel.querySelector('footer time')!.getAttribute('datetime')).toBe(received);
    expect(logs).toHaveBeenCalledTimes(2);
  });

  it('aborts outstanding direct reads when switching hosts', async () => {
    let pending: AbortSignal | undefined;
    vi.spyOn(DemoClient.prototype, 'logs').mockImplementation((_host, _id, signal) => {
      pending = signal;
      return new Promise(() => {});
    });
    await renderDemoApp();
    fireEvent.click(await screen.findByTitle('payments-api'));
    expect(pending?.aborted).toBe(false);
    chooseOption(screen.getByLabelText('Configured host'), 'demo-empty');
    expect(pending?.aborted).toBe(true);
    expect(screen.queryByRole('region', { name: 'Container facts' })).not.toBeInTheDocument();
    expect(await screen.findByText('No containers on this host.')).toBeInTheDocument();
  });
});
