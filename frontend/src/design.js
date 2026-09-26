import { useSyncExternalStore } from 'react';

// ─────────── محرك التصميم: يطبّق ما يُنشر من «استوديو التصميم» في لوحة التحكم على كل الصفحات ───────────
const API = import.meta.env.VITE_API_URL ?? '';
const KEY = 'aw_design';
export const PREVIEW = new URLSearchParams(window.location.search).has('preview');

// نسخة مطابقة للافتراضي في الخادم (تعمل حتى قبل وصول الرد وبلا اتصال)
export const DEFAULT_DESIGN = {
  tokens: {
    dark: { accent: '#ff8a00', accent2: '#ff5a00', bg: '#000000', surface: '#100e0c', text: '#f5efe8', muted: '#8c8378', ok: '#3ddc97', danger: '#ff6b5e' },
    light: { accent: '#e87800', accent2: '#f05200', bg: '#f6f2ec', surface: '#ffffff', text: '#1b1612', muted: '#6e655b', ok: '#12a26b', danger: '#d9443a' },
    font_body: 'plex', font_display: 'chakra', density: 'comfortable', button_shape: 'angled', card_style: 'glass', default_theme: 'dark',
    radius: 14, ui_scale: 100, max_width: 440, glow: 60, fluid: true, animations: true,
  },
  pages: {
    start: { blocks: ['logo', 'stepper', 'title', 'options', 'perks'].map((id) => ({ id, visible: true })), logo_size: 54,
      perks: [{ icon: 'bolt', text_ar: '', text_en: '' }, { icon: 'chart', text_ar: '', text_en: '' }, { icon: 'lock', text_ar: '', text_en: '' }] },
    home: {
      blocks: ['who', 'feedback', 'hero', 'announce', 'subscription', 'scratch', 'quick', 'growth'].map((id) => ({ id, visible: true })),
      hero: { sparkline: true, stats: true, balance_size: 100, today: true, eye: true },
      quick: { items: [{ id: 'support', icon: 'headset' }, { id: 'notifications', icon: 'bell' }, { id: 'billing', icon: 'history' }, { id: 'faq', icon: 'question' }], columns: 4 },
      growth: { cells: ['week', 'month', 'winrate', 'drawdown'] },
    },
    nav: { items: [['main', 'home'], ['analytics', 'analytics'], ['referral', 'referral'], ['rewards', 'rewards'], ['plans', 'plans'], ['settings', 'settings']].map(([id, icon]) => ({ id, icon, visible: true })), labels: true },
    topbar: { theme_toggle: true, support: true, bell: true, logo_size: 26 },
    landing: { title_ar: 'افتح AW ROBOT في تلجرام', title_en: 'Open AW ROBOT in Telegram', sub_ar: 'التطبيق يعمل داخل تلجرام فقط. امسح الرمز بهاتفك أو اضغط الزر.',
      sub_en: 'The app runs inside Telegram. Scan the code with your phone or tap the button.', button_ar: 'فتح في تلجرام', button_en: 'Open in Telegram', show_qr: true, show_features: true },
  },
  texts: { ar: {}, en: {} },
  seo: {},
};

function readCache() {
  try {
    const d = JSON.parse(localStorage.getItem(KEY) || 'null');
    return d && d.tokens ? d : null;
  } catch {
    return null;
  }
}

let current = readCache() || DEFAULT_DESIGN;
const subs = new Set();

export const getDesign = () => current;
export function useDesign() {
  return useSyncExternalStore((f) => { subs.add(f); return () => subs.delete(f); }, getDesign);
}

export function setDesign(d, { persist = !PREVIEW } = {}) {
  if (!d || !d.tokens) return;
  current = d;
  applyDesign(d);
  if (persist) {
    try {
      localStorage.setItem(KEY, JSON.stringify(d));
    } catch {
      /* تخزين غير متاح */
    }
  }
  subs.forEach((f) => f());
}

export async function loadDesign() {
  try {
    const res = await fetch(`${API}/api/design`);
    if (res.ok) setDesign(await res.json());
  } catch {
    /* بلا اتصال: يبقى آخر تصميم محفوظ على الجهاز */
  }
}

// ─────────── تحويل التصميم إلى متغيرات CSS ───────────
const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
const rgb = (h) => hex(h).join(', ');
function mix(a, b, w) {
  const A = hex(a);
  const B = hex(b);
  return `#${A.map((x, i) => Math.round(x + (B[i] - x) * w).toString(16).padStart(2, '0')).join('')}`;
}
const FONTS = {
  plex: "'IBM Plex Sans Arabic', system-ui, -apple-system, 'Segoe UI', sans-serif",
  chakra: "'Chakra Petch', 'IBM Plex Sans Arabic', system-ui, sans-serif",
  system: "system-ui, -apple-system, 'Segoe UI', Roboto, 'Noto Sans Arabic', sans-serif",
};

function modeVars(m, glow) {
  return [
    `--ember:${m.accent}`, `--flame:${m.accent2}`, `--void:${m.bg}`, `--void-rgb:${rgb(m.bg)}`, `--bone:${m.text}`, `--bone-rgb:${rgb(m.text)}`,
    `--ash:${m.muted}`, `--ok:${m.ok}`, `--danger:${m.danger}`, `--surface:${m.surface}`, `--surface-2:${mix(m.surface, m.text, 0.035)}`,
    `--surface-3:${mix(m.surface, m.bg, 0.5)}`, `--surface-4:${mix(m.surface, m.accent, 0.04)}`, `--fill:rgba(${rgb(m.accent)}, 0.06)`,
    `--line:rgba(${rgb(m.accent)}, 0.3)`, `--glow-c:rgba(${rgb(m.accent)}, ${(0.45 * glow) / 60})`,
  ].join(';');
}

let resizeBound = false;
function applyScale(t) {
  const vw = Math.min(window.innerWidth, 760);
  const fit = t.fluid ? Math.max(0.88, Math.min(1.12, vw / 390)) : 1;
  const z = ((t.ui_scale || 100) / 100) * fit;
  document.documentElement.style.setProperty('--ui-zoom', String(Math.round(z * 1000) / 1000));
}

export function applyDesign(d) {
  const t = d.tokens || DEFAULT_DESIGN.tokens;
  const glow = t.glow ?? 60;
  const css = `:root{${modeVars(t.dark, glow)};--font-body:${FONTS[t.font_body] || FONTS.plex};--font-display:${FONTS[t.font_display] || FONTS.chakra};`
    + `--r-card:${t.radius}px;--ui-max:${t.max_width}px;--glow:${glow / 100}}`
    + `html[data-theme='light']{${modeVars(t.light, glow * 0.5)}}`;
  let el = document.getElementById('aw-design');
  if (!el) {
    el = document.createElement('style');
    el.id = 'aw-design';
    document.head.appendChild(el);
  }
  el.textContent = css;
  const root = document.documentElement.dataset;
  root.btn = t.button_shape;
  root.cards = t.card_style;
  root.density = t.density;
  root.anim = t.animations ? 'on' : 'off';
  applyScale(t);
  if (!resizeBound) {
    resizeBound = true;
    window.addEventListener('resize', () => applyScale(current.tokens || DEFAULT_DESIGN.tokens));
  }
}

// ترتيب/إظهار عناصر صفحة (مع ضمان وجود العناصر الافتراضية)
export function blocksOf(page) {
  const rows = current.pages?.[page]?.blocks || DEFAULT_DESIGN.pages[page].blocks;
  return rows.filter((b) => b.visible !== false).map((b) => b.id);
}

applyDesign(current);
