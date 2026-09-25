import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// رقم نسخة لكل بناء: يُضمَّن في الكود ويُكتب في version.json، فتكتشف الأجهزة المفتوحة التحديث وتطبّقه فورًا
const BUILD_ID = `${Date.now().toString(36)}`;

const versionFile = () => ({
  name: 'aw-version-file',
  generateBundle() {
    this.emitFile({ type: 'asset', fileName: 'version.json', source: JSON.stringify({ v: BUILD_ID }) });
  },
});

export default defineConfig({
  plugins: [react(), versionFile()],
  define: { __BUILD_ID__: JSON.stringify(BUILD_ID) },
  build: {
    chunkSizeWarningLimit: 700,
    rollupOptions: {
      output: {
        // فصل المكتبات الثقيلة عن كود التطبيق: تحميل أول أسرع وتخزين مؤقت أطول لما لا يتغير
        manualChunks(id) {
          if (id.includes('node_modules')) {
            if (id.includes('@tonconnect')) return 'tonconnect';
            if (id.includes('react')) return 'react';
            return 'vendor';
          }
          return undefined;
        },
      },
    },
  },
});
