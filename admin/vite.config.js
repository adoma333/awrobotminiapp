import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';

export default defineConfig({
  base: '/admin/',
  plugins: [react()],
  // أيقونات التطبيق نفسها في استوديو التصميم (مصدر واحد) — React واحدة فقط
  resolve: { alias: { '@app': fileURLToPath(new URL('../frontend/src', import.meta.url)) }, dedupe: ['react', 'react-dom'] },
  server: { port: 5174, fs: { allow: ['..'] } },
});
