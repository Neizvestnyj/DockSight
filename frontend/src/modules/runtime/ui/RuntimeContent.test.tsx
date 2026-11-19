import '@testing-library/jest-dom/vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { LogContent } from './RuntimeContent';

afterEach(cleanup);

it('identifies the chronological tail window with dates across midnight', () => {
  const { container } = render(
    <LogContent
      logs={{
        entries: [
          { message: 'Earlier event in this tail', timestamp: '2026-10-27T23:59:59Z' },
          { message: 'database system is shut down', timestamp: '2026-10-28T00:00:01Z' },
        ],
        truncated: true,
      }}
    />,
  );
  expect(screen.getByText('Latest log window · oldest first')).toBeInTheDocument();
  expect(container.querySelector('.log-window')).toHaveTextContent('2026-10-27 23:59:59 UTC');
  expect(container.querySelector('.log-window')).toHaveTextContent('2026-10-28 00:00:01 UTC');
  expect(container.querySelector('.log-line:last-child code')).toHaveTextContent('database system is shut down');
});

it('distinguishes a clipped empty tail from a genuinely empty log', () => {
  render(<LogContent logs={{ entries: [], truncated: true }} />);
  expect(screen.getByText('No complete log lines fit within the limit. The log is incomplete.')).toBeInTheDocument();
  expect(
    screen.queryByText('No log entries returned. An empty log does not establish the cause.'),
  ).not.toBeInTheDocument();
});
