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
    // التقسيم يتم بتحميل الصفحات عند الطلب (React.lazy) فقط. لا manualChunks: تقسيم المكتبات يدويًا
    // سبّب اعتمادًا دائريًا بين الحِزم (Cannot access before initialization) فظهرت شاشة سوداء.
    chunkSizeWarningLimit: 700,
  },
});
