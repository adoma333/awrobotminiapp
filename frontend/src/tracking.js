import { initData, tg } from './telegram';

// ─────────── تتبّع الزوار والأداء (بيانات أولية لخادمنا) + بكسلات المنصات الاختيارية ───────────
const API = import.meta.env.VITE_API_URL ?? '';
const OFF = import.meta.env.DEV && !initData; // معاينة المتصفح أثناء التطوير: لا إرسال
const QS = new URLSearchParams(window.location.search);
const rid = () => (crypto.randomUUID?.() || `${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`).replace(/[^A-Za-z0-9]/g, '').slice(0, 24);

function stored(store, key) {
  try {
    let v = store.getItem(key);
    if (!v || v.length < 8) {
      v = rid();
      store.setItem(key, v);
    }
    return v;
  } catch {
    return rid();
  }
}

const state = { vid: '', sid: '', queue: [], timer: null, page: '', started: false, pixels: null, enabled: true, lang: '' };

function device() {
  return {
    tg_platform: tg?.platform || '', tg_version: tg?.version || '',
    w: window.screen?.width || window.innerWidth, h: window.screen?.height || window.innerHeight,
    theme: document.documentElement.dataset.theme || '',
  };
}

function source() {
  return {
    start_param: String(tg?.initDataUnsafe?.start_param || QS.get('startapp') || ''),
    src: QS.get('utm_source') || '', campaign: QS.get('utm_campaign') || '', medium: QS.get('utm_medium') || '',
  };
}

function flush(beacon = false) {
  clearTimeout(state.timer);
  state.timer = null;
  if (OFF || !state.enabled || !state.queue.length) return;
  const events = state.queue.splice(0, 40);
  const body = JSON.stringify({ init_data: initData, vid: state.vid, sid: state.sid, lang: state.lang, device: device(), source: source(), events });
  if (beacon && navigator.sendBeacon) {
    navigator.sendBeacon(`${API}/api/track`, new Blob([body], { type: 'application/json' }));
  } else {
    fetch(`${API}/api/track`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body, keepalive: true }).catch(() => {});
  }
  if (state.queue.length) flush(beacon);
}

function push(ev) {
  state.queue.push({ ...ev, t: Date.now() });
  if (state.queue.length >= 12) flush();
  else if (!state.timer) state.timer = setTimeout(flush, 4000);
}

// ─────────── قياس الأداء من جهاز المستخدم ───────────
function measurePerf() {
  const out = {};
  try {
    const nav = performance.getEntriesByType?.('navigation')?.[0];
    if (nav) {
      out.ttfb = Math.round(nav.responseStart);
      out.load = Math.round(nav.loadEventEnd || nav.domComplete || 0);
    }
    const fcp = performance.getEntriesByName?.('first-contentful-paint')?.[0];
    if (fcp) out.fcp = Math.round(fcp.startTime);
  } catch {
    /* متصفح قديم */
  }
  let lcp = 0;
  try {
    const po = new PerformanceObserver((list) => {
      const last = list.getEntries().at(-1);
      if (last) lcp = Math.round(last.startTime);
    });
    po.observe({ type: 'largest-contentful-paint', buffered: true });
    setTimeout(() => {
      po.disconnect();
      push({ type: 'perf', props: { ...out, ...(lcp ? { lcp } : {}) } });
    }, 6000);
  } catch {
    setTimeout(() => push({ type: 'perf', props: out }), 6000);
  }
}

export function initTracking() {
  if (state.started) return;
  state.started = true;
  state.vid = stored(localStorage, 'aw_vid');
  state.sid = stored(sessionStorage, 'aw_sid');
  push({ type: 'session_start' });
  if (document.readyState === 'complete') measurePerf();
  else window.addEventListener('load', measurePerf, { once: true });
  setInterval(() => {
    if (document.visibilityState === 'visible') push({ type: 'heartbeat' });
  }, 30000);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') {
      push({ type: 'session_end', page: state.page });
      flush(true);
    }
  });
}

export function setTrackingLang(lang) {
  state.lang = lang;
}

/** مشاهدة صفحة/شاشة داخل التطبيق. */
export function trackPage(page) {
  if (!page || page === state.page) return;
  state.page = page;
  push({ type: 'page_view', page });
  pixel('PageView', {});
}

/** حدث: register · link_account · checkout_open · purchase · support_open · share · scratch_reveal … */
export function trackEvent(name, props = {}) {
  push({ type: 'event', name, page: state.page, props });
  const map = { register: 'CompleteRegistration', link_account: 'CompleteRegistration', checkout_open: 'InitiateCheckout', purchase: 'Purchase', support_open: 'Contact', share: 'Share' };
  if (map[name]) pixel(map[name], props);
}

// ─────────── البكسلات (تُحمَّل فقط إن ضبط الأدمن معرّفاتها) ───────────
function script(src) {
  const s = document.createElement('script');
  s.async = true;
  s.src = src;
  document.head.appendChild(s);
}

export function setupPixels(settings) {
  if (!settings) return;
  state.enabled = settings.analytics !== false;
  const px = settings.pixels || {};
  if (state.pixels || !Object.values(px).some(Boolean)) return;
  state.pixels = px;
  const w = window;
  if (px.meta_pixel) {
    /* eslint-disable */
    !(function (f, b, e, v, n, t, s) { if (f.fbq) return; n = f.fbq = function () { n.callMethod ? n.callMethod.apply(n, arguments) : n.queue.push(arguments); }; if (!f._fbq) f._fbq = n; n.push = n; n.loaded = !0; n.version = '2.0'; n.queue = []; })(w);
    /* eslint-enable */
    script('https://connect.facebook.net/en_US/fbevents.js');
    w.fbq('init', px.meta_pixel);
  }
  if (px.tiktok_pixel) {
    w.TiktokAnalyticsObject = 'ttq';
    const q = (w.ttq = w.ttq || []);
    ['page', 'track', 'identify'].forEach((m) => { q[m] = (...a) => q.push([m, ...a]); });
    script(`https://analytics.tiktok.com/i18n/pixel/events.js?sdkid=${encodeURIComponent(px.tiktok_pixel)}&lib=ttq`);
  }
  if (px.ga4_id) {
    w.dataLayer = w.dataLayer || [];
    w.gtag = function gtag() { w.dataLayer.push(arguments); }; // eslint-disable-line prefer-rest-params
    w.gtag('js', new Date());
    w.gtag('config', px.ga4_id, { send_page_view: false });
    script(`https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(px.ga4_id)}`);
  }
  if (px.x_pixel) {
    const t = (w.twq = w.twq || function twq(...a) { t.queue.push(a); });
    t.queue = t.queue || [];
    t.version = '1.1';
    script('https://static.ads-twitter.com/uwt.js');
    w.twq('config', px.x_pixel);
  }
  if (px.snap_pixel) {
    const s = (w.snaptr = w.snaptr || function snaptr(...a) { s.queue.push(a); });
    s.queue = s.queue || [];
    script('https://sc-static.net/scevent.min.js');
    w.snaptr('init', px.snap_pixel, {});
  }
  if (state.page) pixel('PageView', {});
}

function pixel(name, props) {
  const px = state.pixels;
  if (!px) return;
  const w = window;
  const value = Number(props?.usd) || undefined;
  const money = value ? { value, currency: 'USD' } : {};
  try {
    if (px.meta_pixel && w.fbq) w.fbq('track', name, money);
    if (px.tiktok_pixel && w.ttq) {
      const tt = { PageView: null, CompleteRegistration: 'CompleteRegistration', InitiateCheckout: 'InitiateCheckout', Purchase: 'CompletePayment', Contact: 'Contact', Share: null }[name];
      if (name === 'PageView') w.ttq.page();
      else if (tt) w.ttq.track(tt, money);
    }
    if (px.ga4_id && w.gtag) {
      const ga = { PageView: 'page_view', CompleteRegistration: 'sign_up', InitiateCheckout: 'begin_checkout', Purchase: 'purchase', Contact: 'generate_lead', Share: 'share' }[name];
      w.gtag('event', ga, { ...money, page_title: state.page });
    }
    if (px.x_pixel && w.twq) w.twq('event', px.x_pixel, money);
    if (px.snap_pixel && w.snaptr) {
      const sn = { PageView: 'PAGE_VIEW', CompleteRegistration: 'SIGN_UP', InitiateCheckout: 'START_CHECKOUT', Purchase: 'PURCHASE', Contact: 'CUSTOM_EVENT_1', Share: 'SHARE' }[name];
      w.snaptr('track', sn, value ? { price: value, currency: 'USD' } : {});
    }
  } catch {
    /* بكسل خارجي فشل: لا يؤثر على التطبيق */
  }
}
