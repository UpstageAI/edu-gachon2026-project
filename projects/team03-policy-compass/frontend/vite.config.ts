import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

// FastAPI 백엔드 주소. dev 서버에서 /api 요청을 프록시해서 CORS 없이 상대 경로로 호출한다.
const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000'

export default defineConfig(({ command }) => ({
  // FastAPI serves the production bundle from /static. Keep the development
  // server at / so local Vite URLs and its /api proxy continue to work.
  base: command === 'build' ? '/static/' : '/',
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: BACKEND_URL,
        changeOrigin: true,
      },
    },
  },
  preview: {
    host: '0.0.0.0',
    port: 5173,
  },
}))
