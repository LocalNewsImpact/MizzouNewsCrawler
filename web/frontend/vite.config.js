import { defineConfig } from 'vite'

// Minimal proxy so frontend can call /api/* and it will be forwarded to backend
// Use environment variable to switch between local and remote backend
const API_TARGET = process.env.VITE_API_TARGET || 'http://127.0.0.1:8000'

export default defineConfig({
  server: {
    host: true,
    proxy: {
      '/api': {
        target: API_TARGET,
        changeOrigin: true,
        secure: false,
      }
    }
  }
})
