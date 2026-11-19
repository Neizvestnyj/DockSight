import '@testing-library/jest-dom/vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { DemoClient, demoAnswer } from '../../../infrastructure/demo/demo';
import type { Action } from '../../../shared/contracts/contracts';
import { ActionReview } from './ActionReview';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

/** Supply a complete prepared action with a stable, exact target. */
function prepared(): Action {
  const widget = demoAnswer('crash_loop').widgets.find((row) => row.widget_type === 'container_status')!;
  return { ...widget.actions[0]!, operation: 'stop', container_id: 'a'.repeat(64) };
}

const mismatches: [string, Partial<Action>][] = [
  ['id', { id: 'foreign-action' }],
  ['host', { host: 'foreign-host' }],
  ['container', { container_id: `${'a'.repeat(63)}b` }],
  ['operation', { operation: 'restart' }],
];

it('blocks retry after a failed read until a matching explicit read restores the retained key', async () => {
  const action = prepared();
  const client = new DemoClient();
  client.action = vi
    .fn()
    .mockResolvedValueOnce(action)
    .mockRejectedValueOnce(new Error('offline'))
    .mockResolvedValue(action);
  const execute = vi.fn().mockResolvedValue({ ...action, state: 'succeeded' });
  client.execute = execute;
  const update = vi.fn();
  const keys = new Map([[action.id, 'original-key']]);
  render(<ActionReview action={action} client={client} keys={keys} demo close={() => {}} update={update} />);
  expect(await screen.findByRole('button', { name: 'Retry confirmed stop' })).toBeEnabled();
  fireEvent.click(screen.getByRole('button', { name: 'Check existing action' }));
  expect(await screen.findByRole('alert')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Retry confirmed stop' })).not.toBeInTheDocument();
  expect(execute).not.toHaveBeenCalled();
  expect(update).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: 'Check existing action' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Retry confirmed stop' }));
  await waitFor(() => expect(execute).toHaveBeenCalledWith(action.id, 'original-key'));
  expect(execute).toHaveBeenCalledTimes(1);
});

it.each(mismatches)('rejects a follow-up read with a different %s', async (_field, changes) => {
  const action = prepared();
  const foreign = { ...action, ...changes };
  const client = new DemoClient();
  client.action = vi.fn().mockResolvedValueOnce(action).mockResolvedValueOnce(foreign);
  const execute = vi.fn();
  client.execute = execute;
  const update = vi.fn();
  render(
    <ActionReview
      action={action}
      client={client}
      keys={new Map([[action.id, 'original-key']])}
      demo
      close={() => {}}
      update={update}
    />,
  );
  expect(await screen.findByRole('button', { name: 'Retry confirmed stop' })).toBeEnabled();
  fireEvent.click(screen.getByRole('button', { name: 'Check existing action' }));
  expect(await screen.findByRole('alert')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /Retry confirmed|Confirm restart/ })).not.toBeInTheDocument();
  expect(screen.getByRole('dialog')).toHaveTextContent(action.container_id);
  expect(screen.getByRole('dialog')).toHaveTextContent(action.host);
  expect(update).toHaveBeenCalledTimes(1);
  expect(update).toHaveBeenCalledWith(action);
  expect(execute).not.toHaveBeenCalled();
});

it.each(
  mismatches.flatMap(([field, changes]) => [
    [`direct ${field}`, changes, false] as const,
    [`recovered ${field}`, changes, true] as const,
  ]),
)('rejects a %s execution outcome without retargeting', async (_label, changes, recovery) => {
  const action = prepared();
  const foreign = { ...action, ...changes, state: 'succeeded' as const };
  const client = new DemoClient();
  client.action = recovery
    ? vi.fn().mockResolvedValueOnce(action).mockResolvedValueOnce(foreign).mockResolvedValue(action)
    : vi.fn().mockResolvedValue(action);
  const execute = recovery
    ? vi
        .fn()
        .mockRejectedValueOnce(new Error('lost response'))
        .mockResolvedValue({ ...action, state: 'succeeded' })
    : vi
        .fn()
        .mockResolvedValueOnce(foreign)
        .mockResolvedValue({ ...action, state: 'succeeded' });
  client.execute = execute;
  const update = vi.fn();
  const keys = new Map([[action.id, 'original-key']]);
  render(<ActionReview action={action} client={client} keys={keys} demo close={() => {}} update={update} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Retry confirmed stop' }));
  expect(await screen.findByRole('alert')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /Retry confirmed|Confirm restart/ })).not.toBeInTheDocument();
  expect(screen.getByRole('dialog')).toHaveTextContent(action.container_id);
  expect(screen.getByRole('dialog')).toHaveTextContent(action.host);
  expect(update).toHaveBeenCalledTimes(1);
  expect(update).toHaveBeenCalledWith(action);
  expect(execute).toHaveBeenCalledOnce();
  expect(execute).toHaveBeenCalledWith(action.id, 'original-key');
  fireEvent.click(screen.getByRole('button', { name: 'Check existing action' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Retry confirmed stop' }));
  await waitFor(() => expect(execute).toHaveBeenCalledTimes(2));
  expect(execute).toHaveBeenLastCalledWith(action.id, 'original-key');
});

it('keeps the original selection when a parent rerenders the same action id with another target', async () => {
  const action = prepared();
  const foreign = { ...action, host: 'foreign-host' };
  const client = new DemoClient();
  client.action = vi.fn().mockResolvedValueOnce(action).mockResolvedValue(foreign);
  const update = vi.fn();
  const props = { client, keys: new Map([[action.id, 'original-key']]), demo: true, close: () => {}, update };
  const view = render(<ActionReview {...props} action={action} />);
  expect(await screen.findByRole('button', { name: 'Retry confirmed stop' })).toBeEnabled();
  view.rerender(<ActionReview {...props} action={foreign} />);
  fireEvent.click(screen.getByRole('button', { name: 'Check existing action' }));
  expect(await screen.findByRole('alert')).toBeInTheDocument();
  expect(update).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('dialog')).toHaveTextContent(action.host);
});

it('blocks prior confirmation when a replacement client cannot read the selected action', async () => {
  const action = prepared();
  const first = new DemoClient();
  first.action = vi.fn().mockResolvedValue(action);
  const replacement = new DemoClient();
  let rejectRead: (reason: Error) => void = () => {};
  replacement.action = vi.fn().mockImplementation(
    () =>
      new Promise((_resolve, reject) => {
        rejectRead = reject;
      }),
  );
  const props = { action, keys: new Map([[action.id, 'original-key']]), demo: true, close: () => {}, update: vi.fn() };
  const view = render(<ActionReview {...props} client={first} />);
  expect(await screen.findByRole('button', { name: 'Retry confirmed stop' })).toBeEnabled();
  view.rerender(<ActionReview {...props} client={replacement} />);
  expect(screen.queryByRole('button', { name: 'Retry confirmed stop' })).not.toBeInTheDocument();
  rejectRead(new Error('offline'));
  expect(await screen.findByRole('alert')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Retry confirmed stop' })).not.toBeInTheDocument();
  expect(props.update).toHaveBeenCalledTimes(1);
});

it.each(['resolve', 'reject'] as const)(
  'ignores an old client check that settles by %s after a replacement read',
  async (settlement) => {
    const action = prepared();
    let finish: (result: Action) => void = () => {};
    let fail: (reason: Error) => void = () => {};
    const first = new DemoClient();
    first.action = vi
      .fn()
      .mockResolvedValueOnce(action)
      .mockImplementationOnce(
        () =>
          new Promise((resolve, reject) => {
            finish = resolve;
            fail = reject;
          }),
      );
    const replacement = new DemoClient();
    replacement.action = vi.fn().mockResolvedValue(action);
    const update = vi.fn();
    const props = { action, keys: new Map([[action.id, 'original-key']]), demo: true, close: () => {}, update };
    const view = render(<ActionReview {...props} client={first} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Check existing action' }));
    view.rerender(<ActionReview {...props} client={replacement} />);
    expect(await screen.findByRole('button', { name: 'Retry confirmed stop' })).toBeEnabled();
    await act(async () => {
      if (settlement === 'resolve') finish({ ...action, state: 'succeeded' });
      else fail(new Error('old client disconnected'));
    });
    expect(screen.getByRole('button', { name: 'Retry confirmed stop' })).toBeEnabled();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(update).toHaveBeenCalledTimes(2);
    expect(update).toHaveBeenLastCalledWith(action);
  },
);
