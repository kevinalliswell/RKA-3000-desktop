import { svelte } from '@sveltejs/vite-plugin-svelte'
import { defineConfig } from 'vite'
import { resolve } from 'node:path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [svelte()],
  server: { port: 1420, strictPort: true },
  build: { rollupOptions: { input: { main: resolve(import.meta.dirname, 'index.html'), report: resolve(import.meta.dirname, 'report.html') } } },
})
