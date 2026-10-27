import '@testing-library/jest-dom/vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import App from './App';
import { ActionReview } from './ActionReview';
import { HostPicker } from './HostPicker';
import { DemoClient, demoAnswer } from './demo';
import { vi } from 'vitest';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('investigation workspace', () => {
  it('keeps host choice open through discovery and restores focus to the remounted breadcrumb', async () => {
    let finish: (rows: { id: string; name: string }[]) => void = () => {};
    vi.spyOn(DemoClient.prototype, 'hosts').mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    render(<App />);
    screen.getByTitle('Workspace: choose host').focus();
    fireEvent.click(screen.getByTitle('Workspace: choose host'));
    expect(screen.getByRole('dialog', { name: 'Choose a host' })).toBeInTheDocument();
    await act(async () =>
      finish([
        { id: 'alpha', name: 'Alpha' },
        { id: 'beta', name: 'Beta' },
      ]),
    );
    const picker = screen.getByRole('dialog', { name: 'Choose a host' });
    expect(within(picker).getByRole('button', { name: /Beta/ })).toBeInTheDocument();
    fireEvent.click(within(picker).getByRole('button', { name: 'Close dialog' }));
    expect(screen.getByTitle('Workspace: choose host')).toHaveFocus();
  });

  it('keeps host selection useful while hosts load, when empty, and after a failed read', () => {
    const retry = vi.fn();
    const props = { hosts: [], host: '', retry, choose: vi.fn(), close: vi.fn(), connect: vi.fn() };
    const view = render(<HostPicker {...props} loading error="" />);
    expect(screen.getByRole('status')).toHaveTextContent('Loading hosts…');
    view.rerender(<HostPicker {...props} loading={false} error="" />);
    expect(screen.getByText('No configured hosts')).toBeInTheDocument();
    view.rerender(<HostPicker {...props} loading={false} error="Host discovery failed" />);
    expect(screen.getByRole('alert')).toHaveTextContent('Host discovery failed');
    fireEvent.click(screen.getByRole('button', { name: 'Retry hosts' }));
    expect(retry).toHaveBeenCalledOnce();
  });

  it('acknowledges refresh, retains rows during loading, and keeps the last list after failure', async () => {
    const rows = await new DemoClient().containers('demo-eu');
    let finish: (value: typeof rows) => void = () => {};
    vi.spyOn(DemoClient.prototype, 'containers')
      .mockResolvedValueOnce(rows)
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finish = resolve;
          }),
      )
      .mockRejectedValueOnce(new Error('Test: Docker is unavailable'));
    render(<App />);
    const refresh = screen.getByRole('button', { name: 'Refresh container inventory' });
    await waitFor(() => expect(refresh).toBeEnabled());
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Keep my investigation draft' } });
    fireEvent.click(refresh);
    expect(refresh).toBeDisabled();
    expect(screen.getByRole('status')).toHaveTextContent('Refreshing container list…');
    expect(screen.getByTitle('payments-api')).toBeInTheDocument();
    await act(async () => finish(rows));
    expect(screen.getByRole('status')).toHaveTextContent('Container list refreshed');
    expect(refresh).toHaveAttribute('title', 'Container list refreshed');
    expect(screen.getByRole('textbox')).toHaveValue('Keep my investigation draft');
    fireEvent.click(refresh);
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Refresh failed'));
    expect(screen.getByTitle('payments-api')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Showing the last received list.');
  });

  it('opens host selection from the workspace breadcrumb and preserves the current investigation until switching', async () => {
    render(<App />);
    await screen.findByRole('button', { name: 'Review stop' });
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Keep this question' } });
    fireEvent.click(screen.getByTitle('Workspace: choose host'));
    let picker = screen.getByRole('dialog', { name: 'Choose a host' });
    expect(picker).toHaveTextContent('Selecting another host starts a separate session.');
    fireEvent.click(within(picker).getByRole('button', { name: /Demo host \/ EU/ }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByRole('textbox')).toHaveValue('Keep this question');
    expect(screen.getByRole('button', { name: 'Review stop' })).toBeInTheDocument();
    fireEvent.click(screen.getByTitle('Workspace: choose host'));
    picker = screen.getByRole('dialog', { name: 'Choose a host' });
    fireEvent.click(within(picker).getByRole('button', { name: /Demo host \/ Empty/ }));
    expect(await screen.findByText('Start an investigation')).toBeInTheDocument();
    expect(screen.getByRole('textbox')).toHaveValue('');
  });

  it('does not create container evidence or actions by choosing a scenario on an empty demo host', async () => {
    render(<App />);
    fireEvent.change(screen.getByLabelText('Configured host'), { target: { value: 'demo-empty' } });
    fireEvent.change(screen.getByLabelText('Demo scenario'), { target: { value: 'oom' } });
    expect(screen.queryByRole('button', { name: 'Review restart' })).not.toBeInTheDocument();
    expect(screen.getByText('No UI cards were returned for this answer.')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Configured host'), { target: { value: 'demo-eu' } });
    fireEvent.change(screen.getByLabelText('Simulated connection'), { target: { value: 'empty' } });
    fireEvent.change(screen.getByLabelText('Demo scenario'), { target: { value: 'dependency' } });
    expect(screen.queryByRole('button', { name: 'Review restart' })).not.toBeInTheDocument();
    expect(screen.getByText('No UI cards were returned for this answer.')).toBeInTheDocument();
  });

  it('checks a running action without sending another mutation and renders the returned failed state', async () => {
    const answer = demoAnswer('crash_loop');
    const card = answer.widgets.find((row) => row.widget_type === 'container_status')!;
    const action = { ...card.actions[0]!, state: 'running' as const, message: 'Docker accepted the command' };
    const client = new DemoClient();
    client.action = vi.fn().mockResolvedValue({ ...action, state: 'failed', message: 'Target changed' });
    client.execute = vi.fn();
    render(<ActionReview action={action} client={client} keys={new Map()} demo close={() => {}} update={() => {}} />);
    expect(screen.getByText('running', { exact: true })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Confirm stop' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Check existing action' }));
    expect(await screen.findByText('failed', { exact: true })).toBeInTheDocument();
    expect(client.execute).not.toHaveBeenCalled();
  });
  it('does not replay a demo result after changing away from and back to a host', async () => {
    render(<App />);
    fireEvent.change(screen.getByLabelText('Demo scenario'), { target: { value: 'oom' } });
    fireEvent.change(screen.getByLabelText('Configured host'), { target: { value: 'demo-empty' } });
    fireEvent.change(screen.getByLabelText('Configured host'), { target: { value: 'demo-eu' } });
    expect(await screen.findByText('Start an investigation')).toBeInTheDocument();
    expect(screen.getByLabelText('Demo scenario')).toHaveValue('oom');
  });
  it('reuses the original execution key only after a read confirms the action is still prepared', async () => {
    const answer = demoAnswer('crash_loop');
    const widget = answer.widgets.find((row) => row.widget_type === 'container_status')!;
    const action = widget.actions[0]!;
    const client = new DemoClient();
    client.action = vi.fn().mockResolvedValue(action);
    client.execute = vi.fn().mockResolvedValue({ ...action, state: 'succeeded' });
    const keys = new Map([[action.id, 'retained-execution-key']]);
    render(<ActionReview action={action} client={client} keys={keys} demo close={() => {}} update={() => {}} />);
    expect(screen.queryByRole('button', { name: 'Confirm stop' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Check existing action' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Retry confirmed stop' }));
    await waitFor(() => expect(client.execute).toHaveBeenCalledWith(action.id, 'retained-execution-key'));
  });
  it('connects a conclusion reference to a focusable evidence observation', async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole('button', { name: 'View log evidence' }));
    expect(screen.getByRole('heading', { name: 'Observation' })).toBeInTheDocument();
    expect(screen.getByLabelText('Evidence observation')).toHaveFocus();
    expect(screen.getAllByText('Docker logs').length).toBeGreaterThan(0);
  });

  it('requires a separate exact-target confirmation before running an action', async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole('button', { name: 'Review stop' }));
    expect(screen.getByRole('dialog')).toHaveTextContent('1'.repeat(64));
    expect(screen.getByRole('dialog')).toHaveTextContent('demo-eu');
    fireEvent.click(screen.getByRole('button', { name: 'Confirm stop' }));
    await waitFor(() => expect(screen.getByText('succeeded', { exact: true })).toBeInTheDocument());
  });

  it('starts an empty separate investigation when the host changes', async () => {
    render(<App />);
    await screen.findByRole('button', { name: 'Review stop' });
    fireEvent.change(screen.getByLabelText('Configured host'), { target: { value: 'demo-empty' } });
    expect(await screen.findByText('Start an investigation')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Review stop' })).not.toBeInTheDocument();
    expect(await screen.findByText('No containers on this host.')).toBeInTheDocument();
  });
});
