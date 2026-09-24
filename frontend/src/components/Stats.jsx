import React from 'react';

// الأرقام لاتينية دائمًا (كما في MT5) حتى في الواجهة العربية
export const fmt = (n, d = 2, sign = false) =>
  n == null || Number.isNaN(n)
    ? '—'
    : new Intl.NumberFormat('en-US', {
        minimumFractionDigits: d,
        maximumFractionDigits: d,
        signDisplay: sign ? 'exceptZero' : 'auto',
      }).format(n);

export const pct = (n) => (n == null ? '—' : `${fmt(n, 2, true)}%`);
export const tone = (n) => (n == null || n === 0 ? 'flat' : n > 0 ? 'up' : 'down');

export function timeAgo(epoch, lang) {
  if (!epoch) return '—';
  const secs = Math.max(0, Math.round(Date.now() / 1000 - epoch));
  const rtf = new Intl.RelativeTimeFormat(lang === 'ar' ? 'ar-u-nu-latn' : 'en', { numeric: 'auto' });
  if (secs < 60) return rtf.format(0, 'second');
  if (secs < 3600) return rtf.format(-Math.round(secs / 60), 'minute');
  if (secs < 86400) return rtf.format(-Math.round(secs / 3600), 'hour');
  return rtf.format(-Math.round(secs / 86400), 'day');
}

export function Row({ label, value, kind, hint, plain }) {
  return (
    <div className="row">
      <span className="row-label">
        {label}
        {hint && <small>{hint}</small>}
      </span>
      <span className={`row-value ${kind || ''}`} dir={plain ? undefined : 'ltr'}>
        {value}
      </span>
    </div>
  );
}

