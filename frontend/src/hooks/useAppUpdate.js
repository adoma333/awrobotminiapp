import { useEffect, useRef, useState } from 'react';

/* global __BUILD_ID__ */
const CURRENT = typeof __BUILD_ID__ !== 'undefined' ? __BUILD_ID__ : 'dev';
const EVERY_MS = 45000;
const IDLE_RELOAD_MS = 25000;

/**
 * وصول التحديثات فورًا لكل الأجهزة المفتوحة: يقارن رقم نسخة التطبيق الحالية بـ /version.json كل 45 ثانية
 * وعند العودة للتطبيق. عند وجود نسخة جديدة: يُعاد التحميل تلقائيًا إن كان المستخدم خاملًا أو التطبيق في الخلفية،
 * وإلا يظهر شريط «تحديث الآن». busyRef.current = true يؤجل الإعادة التلقائية (أثناء دفع/ربط).
 */
export default function useAppUpdate(busyRef) {
  const [ready, setReady] = useState(false);
  const lastInput = useRef(Date.now());

  useEffect(() => {
    if (CURRENT === 'dev') return undefined;
    let stopped = false;
    const reload = () => window.location.reload();
    const check = async () => {
      try {
        const r = await fetch(`/version.json?t=${Date.now()}`, { cache: 'no-store' });
        const { v } = await r.json();
        if (!stopped && v && v !== CURRENT) setReady(true);
      } catch {
        /* لا اتصال: نحاول لاحقًا */
      }
    };
    const onVisible = () => {
      if (document.visibilityState === 'visible') check();
    };
    const onInput = () => {
      lastInput.current = Date.now();
    };
    check();
    const id = setInterval(check, EVERY_MS);
    const idle = setInterval(() => {
      if (!ready || busyRef?.current) return;
      if (document.visibilityState === 'hidden' || Date.now() - lastInput.current > IDLE_RELOAD_MS) reload();
    }, 5000);
    document.addEventListener('visibilitychange', onVisible);
    ['pointerdown', 'keydown', 'touchstart'].forEach((e) => window.addEventListener(e, onInput, { passive: true }));
    return () => {
      stopped = true;
      clearInterval(id);
      clearInterval(idle);
      document.removeEventListener('visibilitychange', onVisible);
      ['pointerdown', 'keydown', 'touchstart'].forEach((e) => window.removeEventListener(e, onInput));
    };
  }, [ready, busyRef]);

  return { ready, apply: () => window.location.reload() };
}
