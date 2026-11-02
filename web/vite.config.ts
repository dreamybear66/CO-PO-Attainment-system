import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The API runs on :8000 (uvicorn api.main:app); in development Vite forwards /api to it.
export default defineConfig({
  plugins: [react()],
  // plain CSS only; an inline config also stops Vite picking up a postcss.config from a parent folder
  css: { postcss: { plugins: [] } },
  server: { proxy: { '/api': 'http://localhost:8000' } },
  preview: { proxy: { '/api': 'http://localhost:8000' } },
})
