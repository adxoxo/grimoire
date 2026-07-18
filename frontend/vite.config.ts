import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

// The dashboard talks to the FastAPI read API on :8731 via a same-origin proxy,
// so there is no CORS dance and no hardcoded host in the client. Port matches the
// React app it replaces; change here and in the API launch command together.
export default defineConfig({
  plugins: [svelte()],
  server: {
    proxy: {
      '/api': 'http://localhost:8731',
    },
  },
})
