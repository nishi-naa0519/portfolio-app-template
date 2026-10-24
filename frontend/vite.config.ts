/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // Read BACKEND_URL from the repository root .env (not exposed to client code).
  const env = loadEnv(mode, '..', 'BACKEND_')
  const backendUrl = env.BACKEND_URL || 'http://localhost:8000'

  return {
    plugins: [react()],
    server: {
      proxy: {
        '/api': backendUrl,
      },
    },
    test: {
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.ts'],
    },
  }
})
