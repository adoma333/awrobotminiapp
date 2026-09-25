import { copyText, openExternal, openTelegramLink, tg } from './telegram';

// ─────────── إعدادات الدعم (رابط بوت الدعم/حساب الدعم) — تُخزَّن محليًا لتعمل حتى مع انقطاع الخادم ───────────
const KEY = 'aw_support';
let cfg = (() => {
  try {
    return JSON.parse(localStorage.getItem(KEY) || '{}');
  } catch {
    return {};
  }
})();
let page = 'main';

export function setSupportConfig(settings, botUsername) {
  if (!settings) return;
  const next = {
    url: settings.support_url || (botUsername ? `https://t.me/${botUsername}` : ''),
    bot: settings.support_bot || '',
    mode: settings.support_mode || (settings.support_url ? 'account' : botUsername ? 'bot' : 'none'),
  };
  if (!next.bot && next.mode === 'none' && botUsername) {
    next.bot = botUsername;
    next.mode = 'bot';
    next.url = `https://t.me/${botUsername}`;
  }
  cfg = next;
  try {
    localStorage.setItem(KEY, JSON.stringify(cfg));
  } catch {
    /* تخزين غير متاح: نكتفي بالذاكرة */
  }
}

export const setSupportPage = (p) => {
  page = p || 'main';
};
export const currentPage = () => page;
export const hasSupport = () => Boolean(cfg.url || cfg.bot);

function open(url) {
  if (/^https:\/\/t\.me\//.test(url)) openTelegramLink(url);
  else openExternal(url);
}

/** يفتح محادثة الدعم مباشرة (سماعة الرأس). */
export function openSupport() {
  const url = cfg.bot ? `https://t.me/${cfg.bot}?start=support` : cfg.url;
  if (url) open(url);
  return Boolean(url);
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
 * زر "تواصل مع الدعم": يسجّل الخطأ في الخادم (إن أمكن) ثم يفتح بوت الدعم بـ /start err_<ref>
 * فيبدأ المساعد المعالجة فورًا. مع حساب دعم بشري: رسالة معبّأة مسبقًا (?text=).
 * في كل الحالات يُنسخ نص الخطأ للحافظة كحل بديل. يعمل مع انقطاع الخادم (رابط t.me عبر تلجرام).
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
  let url = '';
  if (cfg.bot) url = `https://t.me/${cfg.bot}${ref ? `?start=err_${ref.replace('ERR-', '')}` : '?start=support'}`;
  else if (cfg.url && /^https:\/\/t\.me\/[A-Za-z0-9_]+\/?$/.test(cfg.url)) url = `${cfg.url.replace(/\/$/, '')}?text=${encodeURIComponent(text)}`;
  else url = cfg.url;
  if (url) open(url);
  return { ref, opened: Boolean(url), copied: true };
}
