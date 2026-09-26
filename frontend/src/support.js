import { copyText, tg } from './telegram';
import { trackEvent } from './tracking';

// ─────────── مركز الدعم داخل التطبيق: يُفتح من أي شاشة (حتى قبل ربط الحساب) ───────────
const EVT = 'aw:support';
let page = 'main';

export const setSupportPage = (p) => {
  page = p || 'main';
};
export const currentPage = () => page;
export const hasSupport = () => true;

/** يفتح مركز الدعم. opts: { errorRef, draft } — رقم الخطأ يُربط بالتذكرة تلقائيًا. */
export function openSupport(opts = {}) {
  trackEvent('support_open', { from: page, err: opts.errorRef ? 1 : 0 });
  window.dispatchEvent(new CustomEvent(EVT, { detail: { errorRef: opts.errorRef || '', draft: opts.draft || '' } }));
  return true;
}

export function onSupportOpen(fn) {
  const h = (e) => fn(e.detail || {});
  window.addEventListener(EVT, h);
  return () => window.removeEventListener(EVT, h);
}

// ─────────── تفاصيل الخطأ (نص جاهز للإرسال) ───────────
export function errorText(t, e) {
  const when = new Date(e.at || Date.now());
  const lines = [
    t.errMsgIntro,
    `• ${t.errType}: ${t[`errKind_${e.kind}`] || e.kind}`,
    e.code ? `• ${t.errCode}: ${e.code}` : null,
    e.message ? `• ${t.errDetails}: ${e.message}` : null,
    `• ${t.errPage}: ${e.page || page}`,
    `• ${t.errTime}: ${when.toISOString().replace('T', ' ').slice(0, 19)} UTC`,
    `• ${t.errNet}: ${navigator.onLine ? t.errOnline : t.errOffline}`,
    e.ref ? `• ${t.errRef}: ${e.ref}` : null,
    tg?.platform ? `• ${t.errDevice}: ${tg.platform} · v${tg.version || '?'}` : null,
  ];
  return lines.filter(Boolean).join('\n');
}

/**
 * زر "تواصل مع الدعم" في أي رسالة خطأ: يسجّل الخطأ في الخادم (إن أمكن) ثم يفتح مركز الدعم داخل التطبيق
 * مربوطًا برقم الخطأ، فيبدأ المساعد الذكي المعالجة فورًا. نص الخطأ يُنسخ للحافظة احتياطًا (انقطاع الخادم).
 */
export async function contactSupportAbout(t, e, report) {
  let ref = e.ref;
  if (!ref && report && navigator.onLine) {
    try {
      const r = await Promise.race([report(e), new Promise((_, rej) => setTimeout(() => rej(new Error('slow')), 2500))]);
      ref = r?.ref;
    } catch {
      /* الخادم لا يستجيب: نكمل بالنص فقط */
    }
  }
  const text = errorText(t, { ...e, ref });
  await copyText(text).catch(() => {});
  openSupport({ errorRef: ref || '', draft: ref ? '' : text });
  return { ref, opened: true, copied: true };
}
