/// <reference types="vitest/config" />
import { fileURLToPath, URL } from 'node:url'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// El build va a ../app/web, que es lo que sirve FastAPI (y lo que copia la imagen Docker).
// En desarrollo (`npm run dev`) Vite reenvía la API y los avatares al servidor de Python en :8000.
const backend = process.env.FW_BACKEND ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  build: { outDir: '../app/web', emptyOutDir: true, chunkSizeWarningLimit: 900 },
  server: { proxy: { '/api': backend, '/avatars': backend } },
  test: { include: ['src/**/*.test.ts'] },
})
