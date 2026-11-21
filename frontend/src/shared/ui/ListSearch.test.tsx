import '@testing-library/jest-dom/vitest';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { ListSearch } from './ListSearch';

afterEach(cleanup);

it('pages the current query and clears back to the browsing view', async () => {
  const requests: { query: string; before?: string }[] = [];
  render(
    <ListSearch
      label="Search containers"
      empty="No matching containers."
      load={(query, _signal, before) => {
        requests.push({ query, before });
        return Promise.resolve({
          items: before ? ['worker-cache'] : ['worker-api'],
          next_cursor: before ? null : 'second-page',
        });
      }}
      row={(item) => <p key={item}>{item}</p>}
      close={() => undefined}
    />,
  );

  const input = screen.getByRole('searchbox', { name: 'Search containers' });
  expect(input).toHaveFocus();
  fireEvent.change(input, { target: { value: ' worker ' } });
  expect(await screen.findByText('worker-api')).toBeVisible();
  const more = screen.getByRole('button', { name: 'More results' });
  more.focus();
  fireEvent.click(more);
  expect(more).toHaveFocus();
  expect(await screen.findByText('worker-cache')).toBeVisible();
  expect(document.activeElement).toContainElement(screen.getByText('worker-cache'));
  expect(screen.getByText('worker-api')).toBeVisible();
  expect(requests).toEqual([{ query: 'worker' }, { query: 'worker', before: 'second-page' }]);

  fireEvent.click(screen.getByRole('button', { name: 'Clear search' }));
  expect(input).toHaveValue('');
  expect(input).toHaveFocus();
  expect(screen.queryByText('worker-api')).toBeNull();
});

it('ignores an older response that finishes after the search query changes', async () => {
  let release!: (value: { items: string[]; next_cursor: null }) => void;
  const old = new Promise<{ items: string[]; next_cursor: null }>((resolve) => {
    release = resolve;
  });
  let start!: (signal: AbortSignal) => void;
  const started = new Promise<AbortSignal>((resolve) => {
    start = resolve;
  });
  render(
    <ListSearch
      label="Search containers"
      empty="No matching containers."
      load={(query, signal) => {
        if (query === 'old') {
          start(signal);
          return old;
        }
        return Promise.resolve({ items: ['new result'], next_cursor: null });
      }}
      row={(item) => <p key={item}>{item}</p>}
      close={() => undefined}
    />,
  );

  const input = screen.getByRole('searchbox');
  fireEvent.change(input, { target: { value: 'old' } });
  const signal = await started;
  fireEvent.change(input, { target: { value: 'new' } });
  expect(signal.aborted).toBe(true);
  expect(await screen.findByText('new result')).toBeVisible();
  await act(async () => {
    release({ items: ['stale result'], next_cursor: null });
    await old;
  });
  expect(screen.queryByText('stale result')).toBeNull();
});
