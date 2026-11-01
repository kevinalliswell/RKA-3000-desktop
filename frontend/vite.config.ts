import { defineConfig, loadEnv } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

// Browser development mode: the Vite dev server proxies /api to a Python backend started by
// hand. The token is read here (Node side) and by Python only; it is never exposed to the page.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', 'RKA3000_');
  const token = env.RKA3000_API_TOKEN ?? process.env.RKA3000_API_TOKEN ?? '';
  const port = env.RKA3000_API_PORT ?? process.env.RKA3000_API_PORT ?? '8765';
  return {
    plugins: [svelte()],
    clearScreen: false,
    envPrefix: 'RKA3000_PUBLIC_',
    server: {
      port: 5174,
      strictPort: true,
      proxy: {
        '/api': {
          target: `http://127.0.0.1:${port}`,
          headers: { Authorization: `Bearer ${token}` },
        },
      },
    },
    test: {
      environment: 'node',
      include: ['src/**/*.test.ts'],
    },
  };
});
