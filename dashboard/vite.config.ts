import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiTarget = env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:3000'
  const port = Number(env.VITE_DEV_PORT || 5175)
  return {
    plugins: [react()],
    server: {
      port,
      strictPort: false,
      proxy: { '/api': { target: apiTarget, changeOrigin: true } },
    },
  }
})
