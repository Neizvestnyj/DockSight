import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import App from './App';
import { ActionReview } from './ActionReview';
import { DemoClient, demoAnswer } from './demo';
import { vi } from 'vitest';

afterEach(cleanup);

describe('investigation workspace', () => {
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
    fireEvent.change(screen.getByLabelText('Configured host'), { target: { value: 'staging' } });
    fireEvent.change(screen.getByLabelText('Configured host'), { target: { value: 'production-eu' } });
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
    expect(screen.getByRole('dialog')).toHaveTextContent('production-eu');
    fireEvent.click(screen.getByRole('button', { name: 'Confirm stop' }));
    await waitFor(() => expect(screen.getByText('succeeded', { exact: true })).toBeInTheDocument());
  });

  it('starts an empty separate investigation when the host changes', async () => {
    render(<App />);
    await screen.findByRole('button', { name: 'Review stop' });
    fireEvent.change(screen.getByLabelText('Configured host'), { target: { value: 'staging' } });
    expect(await screen.findByText('Start an investigation')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Review stop' })).not.toBeInTheDocument();
    expect(await screen.findByText('No containers on this host.')).toBeInTheDocument();
  });
});
