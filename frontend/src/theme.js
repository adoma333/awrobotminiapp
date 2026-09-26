import { useEffect, useState } from 'react';
import { tg } from './telegram';

// ─────────── الوضع الليلي/النهاري: dark (الافتراضي، هوية AW) · light · auto (يتبع تلجرام/الجهاز) ───────────
const KEY = 'aw_theme';
const COLORS = { dark: '#000000', light: '#f6f2ec' };
const EVT = 'aw:theme';

export function getThemePref() {
  try {
    const v = localStorage.getItem(KEY);
    return v === 'light' || v === 'auto' ? v : 'dark';
  } catch {
    return 'dark';
  }
}

export function resolveTheme(pref = getThemePref()) {
  if (pref === 'light' || pref === 'dark') return pref;
  if (tg?.colorScheme) return tg.colorScheme === 'light' ? 'light' : 'dark';
  return window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

export function applyTheme(pref = getThemePref()) {
  const theme = resolveTheme(pref);
  document.documentElement.dataset.theme = theme;
  const c = COLORS[theme];
  try {
    tg?.setHeaderColor?.(c);
    tg?.setBackgroundColor?.(c);
    tg?.setBottomBarColor?.(c);
  } catch {
    /* نسخة تلجرام قديمة */
  }
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', c);
  return theme;
}

export function setThemePref(pref) {
  try {
    localStorage.setItem(KEY, pref);
  } catch {
    /* تخزين غير متاح: يبقى للجلسة الحالية */
  }
  const theme = applyTheme(pref);
  window.dispatchEvent(new CustomEvent(EVT, { detail: { pref, theme } }));
}

/** [التفضيل، تغييره، الوضع الفعلي] — يتابع تغيّر مظهر تلجرام عند «تلقائي». */
export function useTheme() {
  const [pref, setPref] = useState(getThemePref);
  const [theme, setTheme] = useState(() => resolveTheme(getThemePref()));
  useEffect(() => {
    const onChange = (e) => {
      setPref(e.detail.pref);
      setTheme(e.detail.theme);
    };
    const onTg = () => {
      if (getThemePref() === 'auto') setTheme(applyTheme('auto'));
    };
    window.addEventListener(EVT, onChange);
    tg?.onEvent?.('themeChanged', onTg);
    return () => {
      window.removeEventListener(EVT, onChange);
      tg?.offEvent?.('themeChanged', onTg);
    };
  }, []);
  return [pref, setThemePref, theme];
}
