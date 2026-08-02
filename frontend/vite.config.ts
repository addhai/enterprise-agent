import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api': 'http://localhost:8000',
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
    },
  },
  build: {
    // 直接产出到后端托管的 static/ 目录，使 `npm run build` 后 `uvicorn src.api.server:app`
    // 即可同源托管前端 + 后端 API + /ws/chat（无需手动拷贝）。static/ 已在 .gitignore 中。
    outDir: '../static',
    emptyOutDir: true,
  },
})
