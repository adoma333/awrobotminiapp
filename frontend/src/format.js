// تنسيق موحّد لكل الأرقام والتواريخ في التطبيق: أرقام لاتينية دائمًا (كما في MT5)، نفس الفواصل والكسور
const nf = (d, sign) =>
  new Intl.NumberFormat('en-US', { minimumFractionDigits: d, maximumFractionDigits: d, signDisplay: sign ? 'exceptZero' : 'auto' });

export const fmt = (n, d = 2, sign = false) => (n == null || Number.isNaN(Number(n)) ? '—' : nf(d, sign).format(n));
export const pct = (n, d = 2) => (n == null ? '—' : `${fmt(n, d, true)}%`);
export const tone = (n) => (n == null || n === 0 ? 'flat' : n > 0 ? 'up' : 'down');

// المبالغ: كسور فقط عند الحاجة ($19 · $23.20)
export const amount = (n) => {
  if (n == null || Number.isNaN(Number(n))) return '—';
  const v = Number(n);
  return nf(Number.isInteger(v) ? 0 : 2, false).format(v);
};
export const usd = (n) => (n == null ? '—' : `$${amount(n)}`);
export const usdWhole = (n) => (n == null ? '—' : `$${nf(0, false).format(Math.abs(n))}`);
export const signedUsd = (n) => (n == null ? '—' : `${n < 0 ? '−' : '+'}${usdWhole(n)}`);
export const money = (n, cur) => (n == null ? '—' : `${fmt(n)} ${cur || ''}`.trim());

const DATE_LOCALE = (lang) => (lang === 'ar' ? 'ar-u-nu-latn' : 'en-GB');
export const fmtDate = (epoch, lang) =>
  epoch ? new Date(epoch * 1000).toLocaleDateString(DATE_LOCALE(lang), { year: 'numeric', month: 'short', day: 'numeric' }) : '—';

export function timeAgo(epoch, lang) {
  if (!epoch) return '—';
  const secs = Math.max(0, Math.round(Date.now() / 1000 - epoch));
  const rtf = new Intl.RelativeTimeFormat(lang === 'ar' ? 'ar-u-nu-latn' : 'en', { numeric: 'auto' });
  if (secs < 60) return rtf.format(0, 'second');
  if (secs < 3600) return rtf.format(-Math.round(secs / 60), 'minute');
  if (secs < 86400) return rtf.format(-Math.round(secs / 3600), 'hour');
  return rtf.format(-Math.round(secs / 86400), 'day');
}
