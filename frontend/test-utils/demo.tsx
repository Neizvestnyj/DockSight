import { act, fireEvent, render, screen } from '@testing-library/react';
import App from '../src/App';

/** Enter simulated data explicitly after the session bootstrap decision. */
export async function renderDemoApp() {
  const result = render(<App />);
  await act(async () => {});
  fireEvent.click(screen.getByRole('button', { name: /Explore Demo|Открыть демо/ }));
  return result;
}
