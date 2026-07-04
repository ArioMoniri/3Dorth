import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Frontend 2 dev server. The API runs on :8000; we proxy /api so the SPA can
// fetch /api/parameters, /api/demo/manifest and the static /api/geometry/*.vtp
// files without CORS wrangling during development.
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
