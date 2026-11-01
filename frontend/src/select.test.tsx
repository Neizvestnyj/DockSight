import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import { Select } from './Select';

afterEach(cleanup);

it('does not reopen a dismissed menu when a temporarily disabled control becomes available again', () => {
  const props = { value: 'auto', label: 'Scope', options: [{ value: 'auto', label: 'Automatic' }], onChange: () => {} };
  const view = render(<Select {...props} />);
  fireEvent.click(screen.getByRole('combobox'));
  expect(screen.getByRole('combobox')).toHaveAttribute('aria-expanded', 'true');
  view.rerender(<Select {...props} disabled />);
  expect(screen.getByRole('combobox')).toBeDisabled();
  view.rerender(<Select {...props} />);
  expect(screen.getByRole('combobox')).toHaveAttribute('aria-expanded', 'false');
});

it.each(['ArrowUp', 'x'])('reopens from the controlled value after canceling a tentative choice (%s)', (key) => {
  render(
    <Select
      value="auto"
      label="Scope"
      onChange={() => {}}
      options={[
        { value: 'auto', label: 'Automatic' },
        { value: 'compose', label: 'Compose projects' },
        { value: 'swarm', label: 'Swarm stacks' },
      ]}
    />,
  );
  const control = screen.getByRole('combobox');
  fireEvent.keyDown(control, { key: 'End' });
  fireEvent.keyDown(control, { key: 'Escape' });
  fireEvent.keyDown(control, { key });
  const active = document.getElementById(control.getAttribute('aria-activedescendant') ?? '');
  expect(active).toHaveTextContent('Automatic');
});
