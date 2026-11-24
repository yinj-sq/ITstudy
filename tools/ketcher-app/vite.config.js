import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// 构建产物直接落到 Flask 静态目录；全新离线，无外链。
export default defineConfig({
  plugins: [react()],
  base: '/static/chem-lab/ketcher/',
  resolve: {
    alias: {
      events: 'events/',
      buffer: 'buffer/',
    },
  },
  define: {
    global: 'globalThis',
  },
  worker: {
    format: 'es',
  },
  build: {
    outDir: '../../static/chem-lab/ketcher',
    emptyOutDir: true,
    target: 'es2020',
    sourcemap: false,
    chunkSizeWarningLimit: 30000,
  },
});
