import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// API calls go to /api and are proxied to the FastAPI backend, so the browser never talks to
// data providers and never sees credentials.
const API = process.env.MACROPULSE_API ?? 'http://127.0.0.1:8010'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': API,
      '/health': API,
    },
  },
})
