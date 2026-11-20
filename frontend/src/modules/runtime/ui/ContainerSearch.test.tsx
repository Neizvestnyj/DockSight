import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { DemoClient } from '../../../infrastructure/demo/demo';
import { ContainerSearch } from './ContainerSearch';

afterEach(cleanup);

it('retries an unavailable scoped search and reads details only after a selection', async () => {
  const client = new DemoClient();
  client.setFault('offline');
  const choose = vi.fn();
  const detail = vi.spyOn(client, 'container');
  render(
    <ContainerSearch
      client={client}
      host="demo-eu"
      group={{ kind: 'compose', name: 'commerce' }}
      selected=""
      choose={choose}
      close={() => undefined}
      browsing={<p>Recent containers</p>}
    />,
  );
  expect(screen.getByText('Search scope: demo-eu / commerce')).toBeVisible();
  fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'report' } });
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not load search results.');
  client.setFault('none');
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
  const selected = await screen.findByRole('button', { name: /report-worker.*exited/ });
  expect(detail).not.toHaveBeenCalled();

  client.setFault('offline');
  fireEvent.click(selected);
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not open this container.');
  expect(choose).not.toHaveBeenCalled();
  client.setFault('none');
  fireEvent.click(selected);
  await waitFor(() =>
    expect(choose).toHaveBeenCalledWith(
      expect.objectContaining({
        id: '2'.repeat(64),
        name: 'report-worker',
        host: 'demo-eu',
      }),
    ),
  );
});

it('cancels a pending container open when the operator changes the query', async () => {
  const client = new DemoClient();
  const choose = vi.fn();
  const detail = vi.spyOn(client, 'container');
  render(
    <ContainerSearch
      client={client}
      host="demo-eu"
      selected=""
      choose={choose}
      close={() => undefined}
      browsing={null}
    />,
  );
  const field = screen.getByRole('searchbox');
  fireEvent.change(field, { target: { value: 'report' } });
  fireEvent.click(await screen.findByRole('button', { name: /report-worker/ }));
  const signal = detail.mock.calls[0]?.[2];
  fireEvent.change(field, { target: { value: 'payments' } });
  expect(signal?.aborted).toBe(true);
  expect(await screen.findByRole('button', { name: /payments-api/ })).toBeVisible();
  expect(choose).not.toHaveBeenCalled();
});
