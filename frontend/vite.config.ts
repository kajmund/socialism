import path from 'node:path'
import { fileURLToPath } from 'node:url'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, type ProxyOptions } from 'vite'

const rootDir = path.dirname(fileURLToPath(import.meta.url))
const backendTarget = 'http://127.0.0.1:8000'

const apiPrefixes = [
  'health',
  'help',
  'personas',
  'populations',
  'runs',
  'messages',
  'configurations',
  'catalog',
  'jobs',
  'reports',
  'playground',
  'embeddings',
  'anchor-sets',
] as const

const devProxy: Record<string, ProxyOptions> = Object.fromEntries(
  apiPrefixes.map((prefix) => [
    `/${prefix}`,
    { target: backendTarget, changeOrigin: true },
  ]),
)
devProxy['/ws'] = { target: backendTarget, ws: true, changeOrigin: true }

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(rootDir, './src'),
    },
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: false,
    proxy: devProxy,
  },
})
