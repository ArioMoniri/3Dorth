import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Frontend 2 dev server. The API runs on :8000; we proxy /api so the SPA can
// reach /api/parameters, /api/session, /api/upload, the compute endpoints
// (/api/session/{sid}/analyze|compare) and the returned
// /api/session-geometry/*.vtp files without CORS wrangling during development.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Accept the Host header from Cloudflare quick tunnels (*.trycloudflare.com)
    // and any reverse proxy, so the app is reachable when shared publicly.
    allowedHosts: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  // `vite preview` (serves the production `dist/` build) needs its own proxy
  // block — it does NOT inherit `server.proxy` — so the built app can also
  // reach the API during local/manual verification.
  preview: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
});
