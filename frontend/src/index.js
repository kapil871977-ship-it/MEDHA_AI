import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import App from './App';
import reportWebVitals from './reportWebVitals';

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

// If you want to start measuring performance in your app, pass a function
// to log results (for example: reportWebVitals(console.log))
// or send to an analytics endpoint. Learn more: https://bit.ly/CRA-vitals
reportWebVitals();

// ─── PWA: register the service worker so the app is installable + works offline
// Registered only in production browser builds:
//   - the dev server should not be cached
//   - inside the Capacitor native shell the assets are already bundled on the
//     device, and a service worker there just serves stale files after an app
//     update, so it is deliberately skipped
const isNativeShell =
  typeof window.Capacitor?.isNativePlatform === 'function' &&
  window.Capacitor.isNativePlatform() === true;

if ('serviceWorker' in navigator && process.env.NODE_ENV === 'production' && !isNativeShell) {
  window.addEventListener('load', () => {
    const swUrl = `${process.env.PUBLIC_URL || ''}/service-worker.js`;
    navigator.serviceWorker.register(swUrl).catch((err) => {
      console.warn('Service worker registration failed:', err);
    });
  });
}
