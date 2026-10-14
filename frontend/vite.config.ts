import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'
import { viteMockServe } from 'vite-plugin-mock'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // Deterministic offline verification must not consume a developer's .env.
  const env = (process.env.YAYI_OFFLINE_BUILD === '1'
    ? { VITE_API_BASE: '/api', VITE_API_PROXY: 'http://127.0.0.1:8000' }
    : loadEnv(mode, process.cwd())) as {
    VITE_API_BASE: string
    VITE_API_PROXY: string
  }

  return {
    server: {
      port: 5199,
      strictPort: true,
      watch: { usePolling: true, interval: 500 },
      host: '0.0.0.0',
      proxy: {
        [env.VITE_API_BASE]: {
          target: env.VITE_API_PROXY,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api(?=\/|$)/, ''),
        },
      },
    },
    resolve: {
      alias: [
        {
          find: /^@\//,
          replacement: '/src/',
        },
      ],
    },

    plugins: [
      react(),
      viteMockServe({
        enable: false,
      }),
    ],
  }
})
