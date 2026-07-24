import path from 'node:path'
import { fileURLToPath } from 'node:url'
import tailwindcss from '@tailwindcss/vite'
import vue from '@vitejs/plugin-vue'
import { defineConfig, loadEnv } from 'vite'
import { resolveWorkbenchOrigin } from './config/env'

const rootDir = path.dirname(fileURLToPath(import.meta.url))

export default defineConfig(({mode})=>{const env={...loadEnv(mode,rootDir,''),...process.env};return{
  plugins: [vue(), tailwindcss()],
  define:{'import.meta.env.VITE_WORKBENCH_ORIGIN':JSON.stringify(resolveWorkbenchOrigin(env))},
  resolve: { alias: { '@': path.resolve(rootDir, 'src') } },
  server: {
    port: 3000,
    proxy: { '/api': { target: 'http://localhost:8000', changeOrigin: true } },
  },
  test: {
    environment: 'happy-dom',
    setupFiles: ['./src/tests/setup.ts'],
    restoreMocks: true,
  },
}})
