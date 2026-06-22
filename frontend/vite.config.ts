import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The dashboard talks to the FastAPI read API on :8000 via a same-origin proxy,
// so no CORS dance and no hardcoded host in the client.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:8731',
    },
  },
})
