import bronze from './assets/icons/bronze.webp';
import silver from './assets/icons/silver.webp';
import gold from './assets/icons/gold.webp';
import platinum from './assets/icons/platinum.webp';
import diamond from './assets/icons/diamond.webp';
import master from './assets/icons/master.webp';

// مستويات الإحالة حسب عدد الإحالات الناجحة (صديق ربط حسابه)
export const TIERS = [
  { key: 'bronze', min: 0, img: bronze },
  { key: 'silver', min: 3, img: silver },
  { key: 'gold', min: 10, img: gold },
  { key: 'platinum', min: 25, img: platinum },
  { key: 'diamond', min: 50, img: diamond },
  { key: 'master', min: 100, img: master },
];

export function tierFor(count = 0) {
  let i = 0;
  while (i + 1 < TIERS.length && count >= TIERS[i + 1].min) i += 1;
  const cur = TIERS[i];
  const next = TIERS[i + 1] || null;
  const progress = next ? (count - cur.min) / (next.min - cur.min) : 1;
  return { cur, next, left: next ? next.min - count : 0, progress: Math.max(0, Math.min(1, progress)) };
}

export const referralLink = (data) =>
  data?.referral_code && data?.bot_username ? `https://t.me/${data.bot_username}?start=${data.referral_code}` : null;
