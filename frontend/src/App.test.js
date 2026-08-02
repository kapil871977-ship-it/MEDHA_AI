import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import App from './App';

// Network calls are made on mount; keep them controllable so tests never
// hit a real backend.
const pendingFetch = () => jest.fn(() => new Promise(() => {}));

beforeEach(() => {
  localStorage.clear();
  window.location.hash = '';
  global.fetch = pendingFetch();
});

afterEach(() => {
  jest.restoreAllMocks();
  localStorage.clear();
});

test('App renders without crashing and exposes a single top-level heading', () => {
  const { container } = render(<App />);
  const headings = container.querySelectorAll('h1');
  expect(headings).toHaveLength(1);
  expect(headings[0]).toHaveTextContent('Fortune Guru');
});

test('signed-out users land on the login screen', () => {
  render(<App />);
  expect(screen.getByRole('heading', { name: 'Login' })).toBeInTheDocument();
});

test('login screen can toggle to sign-up', () => {
  render(<App />);
  fireEvent.click(screen.getByText('Account banayein'));
  expect(screen.getByRole('heading', { name: 'Naya Account Banayein' })).toBeInTheDocument();
});

test('login requires both fields before calling the API', () => {
  render(<App />);
  fireEvent.click(screen.getByRole('button', { name: 'Login' }));
  expect(screen.getByText(/dono bharna zaroori hai/i)).toBeInTheDocument();
  expect(global.fetch).not.toHaveBeenCalled();
});

test('a stored token renders the home form instead of the login screen', async () => {
  localStorage.setItem('medha_auth_token', 'stored.token');
  global.fetch = jest.fn(() =>
    Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ authenticated: true, identifier: 'a@b.com' })
    })
  );

  render(<App />);
  expect(await screen.findByRole('heading', { name: 'Basic Details Form' })).toBeInTheDocument();
});

test('an invalid stored session is cleared and sends the user back to login', async () => {
  localStorage.setItem('medha_auth_token', 'expired.token');
  global.fetch = jest.fn(() =>
    Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ authenticated: false })
    })
  );

  render(<App />);

  await waitFor(() => {
    expect(localStorage.getItem('medha_auth_token')).toBeNull();
  });
  expect(await screen.findByRole('heading', { name: 'Login' })).toBeInTheDocument();
});

test('a 401 response clears the session', async () => {
  localStorage.setItem('medha_auth_token', 'stale.token');
  global.fetch = jest.fn(() =>
    Promise.resolve({ ok: false, status: 401, json: () => Promise.resolve({}) })
  );

  render(<App />);

  await waitFor(() => {
    expect(localStorage.getItem('medha_auth_token')).toBeNull();
  });
});

test('the kundli form refuses to submit incomplete birth details', async () => {
  localStorage.setItem('medha_auth_token', 'stored.token');
  global.fetch = jest.fn(() =>
    Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ authenticated: true, identifier: 'a@b.com' })
    })
  );

  render(<App />);
  await screen.findByRole('heading', { name: 'Basic Details Form' });

  fireEvent.click(screen.getByRole('button', { name: /Kundli Nayi Page Mein Kholen/i }));
  expect(screen.getByText(/bharna zaroori hai/i)).toBeInTheDocument();
});
