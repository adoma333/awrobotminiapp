import React, { useCallback, useEffect, useRef, useState } from 'react';
import { trackEvent } from '../tracking';
import ErrorNote from './ErrorNote';
import PageHead from './PageHead';
import {
  checkTonPayment, createCryptoPayment, createStarsPayment, createTonPayment, getCurrencies, getPackages, getRewards, redeemCoupon,
} from '../api';
import { fill } from '../i18n';
import { haptic, openExternal, openInvoice } from '../telegram';
import { payWithTon } from '../ton';
import walletIcon from '../assets/icons/wallet.webp';
import coinIcon from '../assets/icons/crypto.webp';
import starsIcon from '../assets/icons/stars.webp';
import { bestCheckoutReward, countdown, prizeLabel } from '../rewards';
import CryptoPay from './CryptoPay';

import { amount as price, fmtDate } from '../format';

const Check = () => (
  <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m5 12 5 5 9-10" /></svg>
);

function Emblem({ kind }) {
  return (
    <svg className={`emblem is-${kind}`} viewBox="0 0 96 96" width="96" height="96" aria-hidden="true">
      <defs>
        <linearGradient id="pl-grad" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#FF8A00" />
          <stop offset="1" stopColor="#FF5A00" />
        </linearGradient>
      </defs>
      {kind === 'pending' ? (
        <>
          <circle cx="48" cy="48" r="38" fill="none" stroke="rgba(255,138,0,.18)" strokeWidth="3" />
          <circle className="spin" cx="48" cy="48" r="38" fill="none" stroke="url(#pl-grad)" strokeWidth="3" strokeLinecap="round" strokeDasharray="70 170" />
          <circle cx="48" cy="48" r="5" fill="url(#pl-grad)" />
        </>
      ) : (
        <>
          <circle cx="48" cy="48" r="38" fill="none" stroke="#3DDC97" strokeWidth="3" />
          <path d="M31 49l12 12 22-25" fill="none" stroke="#3DDC97" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" />
        </>
      )}
    </svg>
  );
}

/**
 * mode = 'renew' : شاشة الباقات من لوحة الحساب (بعد ربط الحساب — شراء أول باقة أو تجديدها)
 * mode = 'flow'  : غير مستخدم حاليًا (كانت خطوة قبل الربط)
 */
const TON_CHECK_EVERY_MS = 15000; // لا نُثقل toncenter: فحص فوري كل 15ث كحد أقصى (والخادم يفحص كل دقيقة)
const REWARD_ERRORS = ['reward_expired', 'reward_used', 'reward_not_found', 'reward_not_applicable'];

/**
 * الباقات كبطاقات بمزايا كاملة ← "اشترك" ← خطوة طرق الدفع (TON أولًا وموصى بها، العملات الرقمية ببوابتنا، النجوم).
 * mode = 'renew' : من لوحة الحساب (شراء أول باقة أو تجديدها)
 */
export default function Plans({ t, lang, sub, refreshStatus, mode, onContinue, onBack, botUsername, autoTon, preferredReward, settings = {} }) {
  const allow = { ton: settings.pay_ton !== false, crypto: settings.pay_crypto !== false, stars: settings.pay_stars !== false };
  const [packages, setPackages] = useState(null);
  const [tonEnabled, setTonEnabled] = useState(false);
  const [coins, setCoins] = useState([]);
  const [selected, setSelected] = useState(null); // الباقة المختارة ← خطوة الدفع
  const [pickCoin, setPickCoin] = useState(false);
  const [cryptoPay, setCryptoPay] = useState(null); // تفاصيل الدفعة في بوابتنا المخصّصة
  const [reward, setReward] = useState(null);
  const [loadError, setLoadError] = useState(false);
  const [busy, setBusy] = useState('');
  const [msg, setMsg] = useState('');
  const [waiting, setWaiting] = useState(null); // { startExpiry, tonOrder? }
  const [paid, setPaid] = useState(false);
  const [couponOpen, setCouponOpen] = useState(false);
  const [coupon, setCoupon] = useState('');
  const [couponMsg, setCouponMsg] = useState('');
  const [couponId, setCouponId] = useState(null); // كوبون حملة استُرد الآن يُفضَّل على غيره

  const loadReward = useCallback(() => {
    getRewards()
      .then((r) => setReward(bestCheckoutReward(r.rewards, couponId || preferredReward)))
      .catch(() => setReward(null));
  }, [preferredReward, couponId]);

  async function applyCoupon(e) {
    e?.preventDefault();
    const code = coupon.trim().toUpperCase();
    if (code.length < 3) return;
    setCouponMsg('');
    try {
      const r = await redeemCoupon(code);
      haptic.success();
      setCouponId(r.reward_id);
      setCoupon('');
      setCouponOpen(false);
      setCouponMsg(fill(t.couponOk, { v: r.type === 'discount' ? `${r.value}%` : fill(t.couponDays, { n: r.value }) }));
    } catch (err) {
      haptic.error();
      setCouponMsg(t[`coupon_${err.detail}`] || t.coupon_coupon_not_found);
    }
  }
  useEffect(loadReward, [loadReward]);

  const load = useCallback(() => {
    setLoadError(false);
    setPackages(null);
    getPackages()
      .then((r) => {
        setPackages(r.packages || []);
        setTonEnabled(Boolean(r.ton_enabled));
      })
      .catch(() => setLoadError(true));
    getCurrencies().then((r) => setCoins(r.currencies || [])).catch(() => setCoins([]));
  }, []);
  useEffect(load, [load]);

  // السعر المعروض بعد الخصم (للعرض فقط؛ المبلغ الفعلي يحسبه الخادم)
  const discounted = (n, round) => {
    if (!reward || reward.type !== 'discount' || !n) return n;
    const v = n * (1 - reward.value / 100);
    return round ? Math.max(1, Math.round(v)) : v;
  };
  const rewardFailed = (e) => {
    if (!REWARD_ERRORS.includes(e?.detail)) return false;
    setMsg('rwInvalid');
    loadReward();
    return true;
  };

  const selRef = useRef(null);
  selRef.current = selected;
  useEffect(() => {
    if (selected) trackEvent('checkout_open', { pkg: selected.id, usd: selected.price_usd });
  }, [selected]);

  const markPaid = useCallback(() => {
    trackEvent('purchase', { pkg: selRef.current?.id || '', usd: selRef.current?.price_usd || 0 });
    setWaiting(null);
    setCryptoPay(null);
    setPaid(true);
    haptic.success();
  }, []);

  // يفحص تفعيل الاشتراك: ظهور تاريخ انتهاء أبعد من وقت بدء الدفع
  const check = useCallback(async () => {
    if (!waiting) return;
    if (waiting.tonOrder && Date.now() - (waiting.tonCheckedAt || 0) > TON_CHECK_EVERY_MS) {
      waiting.tonCheckedAt = Date.now();
      await checkTonPayment(waiting.tonOrder).catch(() => {});
    }
    try {
      const s = await refreshStatus();
      const sb = s.subscription;
      if (sb?.active && sb.expires_at > waiting.startExpiry + 60) markPaid();
    } catch {
      /* نعيد المحاولة في الدورة التالية */
    }
  }, [waiting, refreshStatus, markPaid]);

  useEffect(() => {
    if (!waiting) return undefined;
    const id = setInterval(check, 4000);
    return () => clearInterval(id);
  }, [waiting, check]);

  // البث اللحظي (SSE) يحدّث sub فور تفعيل الاشتراك
  useEffect(() => {
    if (waiting && sub?.active && sub.expires_at > waiting.startExpiry + 60) markPaid();
  }, [sub?.expires_at, sub?.active, waiting, markPaid]);

  const startWaiting = (extra = {}) => setWaiting({ startExpiry: sub?.expires_at || 0, ...extra });

  async function payCrypto(pkg, coin) {
    setBusy(`crypto:${coin}`);
    setMsg('');
    try {
      const r = await createCryptoPayment(pkg.id, reward?.id, coin);
      setCryptoPay(r);
      setWaiting({ startExpiry: sub?.expires_at || 0 });
    } catch (e) {
      haptic.error();
      if (rewardFailed(e)) return;
      setMsg(e.detail === 'amount_too_low' ? 'payTooLow' : e.detail === 'gateway_busy_retry' ? 'payBusy'
        : ['payment_provider_error', 'rate_unavailable'].includes(e.detail) || String(e.detail || '').startsWith('chain_error') ? 'payProviderErr' : 'payErr');
    } finally {
      setBusy('');
    }
  }

  async function payStars(pkg) {
    setBusy('stars');
    setMsg('');
    try {
      const r = await createStarsPayment(pkg.id, reward?.id);
      const opened = openInvoice(r.invoice_link, (status) => {
        if (status === 'paid') startWaiting();
        else if (status === 'cancelled') setMsg('payCancelled');
        else if (status === 'failed') setMsg('payFailed');
      });
      if (!opened) {
        openExternal(r.invoice_link);
        startWaiting();
      }
    } catch (e) {
      haptic.error();
      if (!rewardFailed(e)) setMsg(e.detail === 'stars_not_configured_for_package' ? 'starsNotReady' : 'payErr');
    } finally {
      setBusy('');
    }
  }

  async function payTon(pkg) {
    setBusy('ton');
    setMsg('');
    try {
      const tx = await createTonPayment(pkg.id, reward?.id);
      await payWithTon(tx, botUsername);
      startWaiting({ tonOrder: tx.order_id });
      checkTonPayment(tx.order_id).catch(() => {});
    } catch (e) {
      haptic.error();
      const cancelled = e?.message === 'ton_cancelled' || e?.constructor?.name === 'UserRejectsError' || /reject/i.test(e?.message || '');
      if (rewardFailed(e)) return;
      if (cancelled) setMsg('payCancelled');
      else if (['ton_not_configured', 'ton_rate_unavailable'].includes(e?.detail)) setMsg('tonNotReady');
      else setMsg('payErr');
    } finally {
      setBusy('');
    }
  }

  // تذكير التجديد (?renew=ton): نفتح خطوة الدفع لباقة المستخدم الحالية ونبدأ TON مباشرة
  const autoTonDone = useRef(false);
  useEffect(() => {
    if (!autoTon || autoTonDone.current || !packages?.length || !tonEnabled) return;
    const pkg = packages.find((p) => p.id === sub?.package_id) || packages[0];
    autoTonDone.current = true;
    setSelected(pkg);
    payTon(pkg);
  }, [autoTon, packages, tonEnabled]);

  const name = (p) => (lang === 'ar' ? p.name_ar || p.name_en : p.name_en || p.name_ar);
  const tagline = (p) => (lang === 'ar' ? p.tagline_ar : p.tagline_en) || '';
  const features = (p) => (lang === 'ar' ? p.features_ar : p.features_en) || [];

  // ───────── حالات خاصة ─────────
  if (paid) {
    return (
      <section className="step status" aria-live="polite">
        <Emblem kind="ok" />
        <h1>{t.paidTitle}</h1>
        <p className="sub">{fill(t.paidBody, { date: fmtDate(sub?.expires_at, lang) })}</p>
        <div className="actions">
          <button type="button" className="btn primary" onClick={onContinue}>
            <span>{t.next}</span>
          </button>
        </div>
      </section>
    );
  }

  if (cryptoPay) {
    return (
      <CryptoPay
        t={t}
        pay={cryptoPay}
        onFinished={() => refreshStatus().then(markPaid).catch(markPaid)}
        onCancel={() => {
          setCryptoPay(null);
          setWaiting(null);
        }}
      />
    );
  }

  if (waiting) {
    return (
      <section className="step status" aria-live="polite">
        <Emblem kind="pending" />
        <h1>{t.payWaitTitle}</h1>
        <p className="sub">{t.payWaitBody}</p>
        <div className="actions stack">
          <button type="button" className="btn primary" onClick={check}>
            <span>{t.payCheck}</span>
          </button>
          <button type="button" className="btn ghost" onClick={() => setWaiting(null)}>
            <span>{t.payCancel}</span>
          </button>
        </div>
      </section>
    );
  }

  const rewardChip = reward && (
    <div className="note reward-applied" role="status">
      <span>🎁 {fill(t.rwApplied, { label: prizeLabel(t, reward) })} · {countdown(t, reward.expires_at, Date.now() / 1000)}</span>
      <button type="button" className="link" onClick={() => setReward(null)}>{t.rwRemove}</button>
    </div>
  );

  // ───────── خطوة طرق الدفع ─────────
  if (selected) {
    const p = selected;
    const usd = discounted(p.price_usd);
    return (
      <section className="step checkout">
        <PageHead t={t} onBack={() => { setSelected(null); setPickCoin(false); setMsg(''); }} />
        <h1>{t.checkoutTitle}</h1>
        <div className="checkout-summary">
          <div>
            <strong>{name(p)}</strong>
            <span className="muted">{fill(t.perDays, { n: p.duration_days })}</span>
          </div>
          <div className="plan-price" dir="ltr">
            {usd !== p.price_usd && <s className="muted">${price(p.price_usd)}</s>} <strong>${price(usd)}</strong>
          </div>
        </div>
        {rewardChip}

        <h2 className="pay-heading">{t.payMethod}</h2>
        <div className="pay-methods">
          {allow.ton && tonEnabled && p.price_ton ? (
            <button type="button" className="pay-method is-best" disabled={!!busy} onClick={() => payTon(p)}>
              <span className="best-badge">{t.tonBest}</span>
              <img src={walletIcon} alt="" className="pm-icon" />
              <span className="pm-body">
                <b>{t.payTonTitle}</b>
                <small>{t.tonPerks}</small>
              </span>
              <span className="pm-amount" dir="ltr">{busy === 'ton' ? '…' : `${price(discounted(p.price_ton))} TON`}</span>
            </button>
          ) : null}

          {allow.crypto && (
          <button type="button" className={`pay-method ${pickCoin ? 'is-open' : ''}`} disabled={!!busy && !busy.startsWith('crypto')} onClick={() => setPickCoin((v) => !v)}>
            <img src={coinIcon} alt="" className="pm-icon" />
            <span className="pm-body">
              <b>{t.payCrypto}</b>
              <small dir="ltr">{coins.map((c) => c.symbol).filter((v, i, a) => a.indexOf(v) === i).join(' · ') || 'USDT · BTC · ETH'}</small>
            </span>
            <span className="pm-amount" dir="ltr">${price(usd)}</span>
          </button>
          )}
          {allow.crypto && pickCoin && (
            <div className="coin-grid">
              {coins.map((c) => (
                <button key={c.code} type="button" className="coin-chip" disabled={!!busy} onClick={() => payCrypto(p, c.code)}>
                  <b>{c.symbol}</b>
                  <small>{busy === `crypto:${c.code}` ? t.sending : c.network}</small>
                </button>
              ))}
            </div>
          )}

          {allow.stars && p.price_stars ? (
            <button type="button" className="pay-method" disabled={!!busy} onClick={() => payStars(p)}>
              <img src={starsIcon} alt="" className="pm-icon" />
              <span className="pm-body">
                <b>{t.payStarsTitle}</b>
                <small>{t.starsPerks}</small>
              </span>
              <span className="pm-amount" dir="ltr">{busy === 'stars' ? '…' : <>{price(discounted(p.price_stars, true))} <img src={starsIcon} alt="" className="cur-ic" /></>}</span>
            </button>
          ) : null}
        </div>

        {msg && <ErrorNote t={t} kind="operation" code={`pay_${msg}`}>{t[msg]}</ErrorNote>}
        <p className="muted small-note">{t.paySecure}</p>
      </section>
    );
  }

  // ───────── بطاقات الباقات ─────────
  return (
    <section className="step">
      <PageHead t={t} onBack={onBack} />
      <h1>{mode === 'renew' && sub ? t.renewTitle : t.plansTitle}</h1>
      <p className="sub">{t.plansSub}</p>

      {sub?.active && (
        <div className="note" role="status">
          <b>{t.currentPlan}: </b>
          {(lang === 'ar' ? sub.package_name_ar : sub.package_name_en) || '—'} ·{' '}
          {fill(t.expiresOn, { date: fmtDate(sub.expires_at, lang) })} ({fill(t.daysLeft, { n: sub.days_left })})
        </div>
      )}
      {rewardChip}
      <div className="coupon-box">
        {couponOpen ? (
          <form className="coupon-form" onSubmit={applyCoupon}>
            <input dir="ltr" autoFocus maxLength={20} value={coupon} placeholder={t.couponPh}
              onChange={(e) => setCoupon(e.target.value.replace(/[^A-Za-z0-9]/g, '').toUpperCase())} />
            <button type="submit" className="btn soft small" disabled={coupon.trim().length < 3}><span>{t.couponApply}</span></button>
          </form>
        ) : (
          <button type="button" className="link coupon-toggle" onClick={() => setCouponOpen(true)}>{t.couponHave}</button>
        )}
        {couponMsg && <p className={`coupon-msg ${couponId ? 'ok' : 'bad'}`} role="status">{couponMsg}</p>}
      </div>

      {packages === null && !loadError && <div className="loader" role="status" aria-label={t.loading} />}
      {loadError && (
        <ErrorNote t={t} kind="operation" code="plans_load_failed">
          {t.plansLoadErr}{' '}
          <button type="button" className="link" onClick={load}>{t.reload}</button>
        </ErrorNote>
      )}
      {packages && packages.length === 0 && <p className="note">{t.noPlans}</p>}

      {packages && packages.length > 0 && (
        <div className="plans">
          {packages.map((p) => (
            <article className={`plan ${p.featured ? 'is-featured' : ''} ${p.private_uid ? 'is-private' : ''}`} key={p.id}>
              {p.featured && <span className="plan-badge">{p.private_uid ? t.privateBadge : tagline(p) || t.mostPopular}</span>}
              <div className="plan-head">
                <div>
                  <h2 className="plan-name" dir="ltr">{name(p)}</h2>
                  {!p.featured && tagline(p) && <span className="plan-tag">{tagline(p)}</span>}
                </div>
                <div className="plan-price" dir="ltr">
                  {discounted(p.price_usd) !== p.price_usd && <s className="muted">${price(p.price_usd)}</s>}{' '}
                  <strong>${price(discounted(p.price_usd))}</strong>
                </div>
              </div>
              <div className="plan-meta">
                {fill(t.perDays, { n: p.duration_days })}
                {p.private_uid && p.offer_expires_at ? <span className="plan-expiry"> · {countdown(t, p.offer_expires_at, Date.now() / 1000)}</span> : null}
              </div>
              {features(p).length > 0 && (
                <ul className="plan-features">
                  {features(p).map((f) => (
                    <li key={f}><Check />{f}</li>
                  ))}
                </ul>
              )}
              <button type="button" className={`btn ${p.featured ? 'primary' : 'soft'}`} onClick={() => { setSelected(p); setMsg(''); }}>
                <span>{t.subscribe}</span>
              </button>
            </article>
          ))}
        </div>
      )}

    </section>
  );
}
