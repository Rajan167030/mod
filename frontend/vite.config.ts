import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The app calls the API on its own origin (/api/v1); the dev server forwards it to the backend.
// That way one public tunnel to this server is enough to demo from any device.
const backend = process.env.AIROPS_BACKEND_URL || 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    // Tunnels (Cloudflare, ngrok) reach the dev server under their own hostnames
    allowedHosts: true,
    proxy: {
      '/api': { target: backend, changeOrigin: true },
      '/health': { target: backend, changeOrigin: true },
    },
  },
})
