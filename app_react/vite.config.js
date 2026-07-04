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
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
});
