import { render } from '@testing-library/react';
import App from './App';

// Network calls are made on mount; keep them pending so the smoke test
// renders the initial screen without hitting the backend.
beforeEach(() => {
  global.fetch = jest.fn(() => new Promise(() => {}));
});

afterEach(() => {
  jest.restoreAllMocks();
});

test('App renders without crashing', () => {
  const { container } = render(<App />);
  expect(container).toBeTruthy();
  expect(container.querySelector('h1')).not.toBeNull();
});
