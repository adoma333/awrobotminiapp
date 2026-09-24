import { fill } from './i18n';

// أنواع الجوائز كما يولّدها الخادم (generate_scratch_prize)
export const CHECKOUT_TYPES = ['discount', 'free_days'];

export function prizeLabel(t, p) {
  const n = p?.value;
  switch (p?.type) {
    case 'discount':
      return fill(t.prizeDiscount, { n });
    case 'free_days':
      return fill(t.prizeFreeDays, { n });
    case 'slippage_insurance':
      return fill(t.prizeInsurance, { n });
    case 'free_month':
      return t.prizeFreeMonth;
    case 'funded_challenge':
      return fill(t.prizeFunded, { n });
    default:
      return '—';
  }
}

export function prizeIcon(type) {
  return { discount: '🏷️', free_days: '📅', slippage_insurance: '🛡️', free_month: '👑', funded_challenge: '🏆' }[type] || '🎁';
}

// عدّاد تنازلي بالساعات والدقائق
export function countdown(t, expiresAt, nowSec) {
  const left = Math.max(0, Math.floor(expiresAt - nowSec));
  const h = Math.floor(left / 3600);
  const m = Math.floor((left % 3600) / 60);
  return fill(t.rwExpiresIn, { h, m: String(m).padStart(2, '0') });
}

// أفضل جائزة صالحة للتطبيق على الدفع: أعلى خصم، وإلا أكثر أيام مجانية
export function bestCheckoutReward(rewards, preferredId) {
  const ok = (rewards || []).filter((r) => r.status === 'active' && CHECKOUT_TYPES.includes(r.type));
  const pref = ok.find((r) => r.id === preferredId);
  if (pref) return pref;
  const disc = ok.filter((r) => r.type === 'discount').sort((a, b) => b.value - a.value)[0];
  return disc || ok.sort((a, b) => b.value - a.value)[0] || null;
}
