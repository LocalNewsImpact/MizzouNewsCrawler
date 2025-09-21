import { defineConfig } from 'vite'

// Minimal proxy so frontend can call /api/* and it will be forwarded to backend
export default defineConfig({
  server: {
    host: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        secure: false,
      }
    }
  }
})
