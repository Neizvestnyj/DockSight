import { chooseOption } from '../test-utils/select';
import '@testing-library/jest-dom/vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import App from './App';
import { DemoClient, demoAnswer, demoContainer } from './demo';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('read-only container viewing', () => {
  it('opens Docker facts without a model request and preserves historical cards and drafts', async () => {
    const diagnose = vi.spyOn(DemoClient.prototype, 'diagnose');
    const scenario = vi.spyOn(DemoClient.prototype, 'setScenario');
    render(<App />);
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
    render(<App />);
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
    render(<App />);
    fireEvent.click(await screen.findByTitle('payments-api'));
    fireEvent.click(screen.getByTitle('report-worker'));
    const facts = screen.getByRole('region', { name: 'Container facts' });
    expect(await within(facts).findByText('137')).toBeInTheDocument();
    await act(async () => finish(demoContainer(0, 'demo-eu', '2026-10-27T12:00:01Z')));
    expect(within(facts).getByRole('heading', { name: 'report-worker' })).toBeInTheDocument();
    expect(within(facts).getByText('137')).toBeInTheDocument();
  });

  it('starts diagnosis only on explicit request for the selected exact container', async () => {
    const diagnose = vi.spyOn(DemoClient.prototype, 'diagnose').mockImplementation(async (input, receive) => {
      const envelope = { schema_version: 1 as const, request_id: 'r', turn_id: 't' };
      receive({ ...envelope, type: 'turn.started', session_id: crypto.randomUUID() });
      receive({ ...envelope, type: 'answer.ready', answer: demoAnswer('oom', input.host) });
      receive({ ...envelope, type: 'turn.completed' });
    });
    render(<App />);
    fireEvent.click(await screen.findByTitle('report-worker'));
    const button = screen.getByRole('button', { name: 'Diagnose' });
    await waitFor(() => expect(button).toBeEnabled());
    expect(diagnose).not.toHaveBeenCalled();
    fireEvent.click(button);
    await screen.findByRole('heading', { name: /Investigate report-worker/ });
    expect(diagnose).toHaveBeenCalledOnce();
    expect(diagnose.mock.calls[0]?.[0]).toEqual({
      host: 'demo-eu',
      query: `Investigate report-worker (${'2'.repeat(64)}). What happened, and what evidence supports it?`,
    });
    expect(screen.getByText('2 turns in this tab session')).toBeInTheDocument();
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
    render(<App />);
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
    render(<App />);
    fireEvent.click(await screen.findByTitle('payments-api'));
    expect(pending?.aborted).toBe(false);
    chooseOption(screen.getByLabelText('Configured host'), 'demo-empty');
    expect(pending?.aborted).toBe(true);
    expect(screen.queryByRole('region', { name: 'Container facts' })).not.toBeInTheDocument();
    expect(await screen.findByText('No containers on this host.')).toBeInTheDocument();
  });
});
