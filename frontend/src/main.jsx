import React from 'react';
import ReactDOM from 'react-dom/client';
import '@fontsource/chakra-petch/600.css';
import '@fontsource/ibm-plex-sans-arabic/400.css';
import '@fontsource/ibm-plex-sans-arabic/500.css';
import '@fontsource/ibm-plex-sans-arabic/600.css';
import './App.css';
import App from './App.jsx';
import { ToastProvider } from './components/Toast';
import { applyTheme } from './theme';
import { loadDesign } from './design';
import { initTracking } from './tracking';

applyTheme(); // قبل أول رسم: لا وميض بين الوضعين
loadDesign().then(() => applyTheme());
initTracking();

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ToastProvider>
      <App />
    </ToastProvider>
  </React.StrictMode>
);
