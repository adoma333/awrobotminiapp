import React, { useCallback, useEffect, useRef, useState } from 'react';
import { checkTonPayment, createPayment, createStarsPayment, createTonPayment, getPackages, getRewards } from '../api';
import { fill } from '../i18n';
import { haptic, openExternal, openInvoice } from '../telegram';
import { payWithTon } from '../ton';
import walletIcon from '../assets/icons/wallet.webp';
import coinIcon from '../assets/icons/coin.webp';
import { bestCheckoutReward, countdown, prizeLabel } from '../rewards';

const fmtDate = (epoch, lang) =>
  epoch
    ? new Date(epoch * 1000).toLocaleDateString(lang === 'ar' ? 'ar-u-nu-latn' : 'en', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
      })
    : '—';

const price = (n) => new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 }).format(n);

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

// بوابة NOWPayments المضمّنة داخل الـ Mini App (iframe) بدل التحويل لمتصفح خارجي
function PayModal({ t, pay, onClose }) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-sheet pay-sheet" onClick={(e) => e.stopPropagation()}>
        <div className="pay-sheet-head">
          <h2>{t.payInAppTitle}</h2>
          <button type="button" className="btn ghost small" onClick={onClose}><span>{t.close}</span></button>
        </div>
        <iframe className="pay-frame" src={pay.widget} title="NOWPayments" allow="clipboard-write" />
        <button type="button" className="link" onClick={() => openExternal(pay.url)}>{t.openInBrowser}</button>
      </div>
    </div>
  );
}

const REWARD_ERRORS = ['reward_expired', 'reward_used', 'reward_not_found', 'reward_not_applicable'];

export default function Plans({ t, lang, sub, refreshStatus, mode, onContinue, onBack, botUsername, autoTon, preferredReward }) {
  const [packages, setPackages] = useState(null);
  const [tonEnabled, setTonEnabled] = useState(false);
  const [payModal, setPayModal] = useState(null); // { widget, url }
  const [reward, setReward] = useState(null); // جائزة خدش صالحة تُطبَّق تلقائيًا (الخادم يتحقق ويحسب المبلغ)

  const loadReward = useCallback(() => {
    getRewards()
      .then((r) => setReward(bestCheckoutReward(r.rewards, preferredReward)))
      .catch(() => setReward(null));
  }, [preferredReward]);
  useEffect(loadReward, [loadReward]);

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
  const [loadError, setLoadError] = useState(false);
  const [busy, setBusy] = useState('');
  const [msg, setMsg] = useState('');
  const [waiting, setWaiting] = useState(null); // { startExpiry }
  const [paid, setPaid] = useState(false);

  const load = useCallback(() => {
    setLoadError(false);
    setPackages(null);
    getPackages()
      .then((r) => {
        setPackages(r.packages || []);
        setTonEnabled(Boolean(r.ton_enabled));
      })
      .catch(() => setLoadError(true));
  }, []);
  useEffect(load, [load]);

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
      if (sb?.active && sb.expires_at > waiting.startExpiry + 60) {
        setWaiting(null);
        setPayModal(null);
        setPaid(true);
        haptic.success();
      }
    } catch {
      /* نعيد المحاولة في الدورة التالية */
    }
  }, [waiting, refreshStatus]);

  useEffect(() => {
    if (!waiting) return undefined;
    const id = setInterval(check, 4000);
    return () => clearInterval(id);
  }, [waiting, check]);

  // البث اللحظي (SSE) يحدّث sub فور تفعيل الاشتراك: نكشف الدفع دون انتظار دورة الفحص
  useEffect(() => {
    if (waiting && sub?.active && sub.expires_at > waiting.startExpiry + 60) {
      setWaiting(null);
      setPayModal(null);
      setPaid(true);
      haptic.success();
    }
  }, [sub?.expires_at, sub?.active, waiting]);

  const startWaiting = (extra = {}) => setWaiting({ startExpiry: sub?.expires_at || 0, ...extra });

  async function payCrypto(pkg) {
    setBusy(`${pkg.id}:crypto`);
    setMsg('');
    try {
      const r = await createPayment(pkg.id, reward?.id);
      if (r.widget_url) setPayModal({ widget: r.widget_url, url: r.invoice_url });
      else openExternal(r.invoice_url);
      startWaiting();
    } catch (e) {
      haptic.error();
      if (!rewardFailed(e)) setMsg(e.detail === 'payment_provider_error' ? 'payProviderErr' : 'payErr');
    } finally {
      setBusy('');
    }
  }

  async function payStars(pkg) {
    setBusy(`${pkg.id}:stars`);
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
    setBusy(`${pkg.id}:ton`);
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
      else if (e?.detail === 'ton_not_configured' || e?.detail === 'ton_not_configured_for_package') setMsg('tonNotReady');
      else setMsg('payErr');
    } finally {
      setBusy('');
    }
  }

  // تذكير التجديد: نبدأ الدفع بـ TON لباقة المستخدم الحالية (أو أول باقة تقبل TON) مرة واحدة
  const autoTonDone = useRef(false);
  useEffect(() => {
    if (!autoTon || autoTonDone.current || !packages || !tonEnabled) return;
    const pkg = packages.find((p) => p.id === sub?.package_id && p.price_ton) || packages.find((p) => p.price_ton);
    if (!pkg) return;
    autoTonDone.current = true;
    payTon(pkg);
  }, [autoTon, packages, tonEnabled]);

  const modal = payModal && <PayModal t={t} pay={payModal} onClose={() => setPayModal(null)} />;

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

  if (waiting) {
    return (
      <section className="step status" aria-live="polite">
        {modal}
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

  // ───────── قائمة الباقات ─────────
  const name = (p) => (lang === 'ar' ? p.name_ar || p.name_en : p.name_en || p.name_ar);

  return (
    <section className="step">
      <h1>{mode === 'renew' && sub ? t.renewTitle : t.plansTitle}</h1>
      <p className="sub">{t.plansSub}</p>

      {sub?.active && (
        <div className="note" role="status">
          <b>{t.currentPlan}: </b>
          {(lang === 'ar' ? sub.package_name_ar : sub.package_name_en) || '—'} ·{' '}
          {fill(t.expiresOn, { date: fmtDate(sub.expires_at, lang) })} ({fill(t.daysLeft, { n: sub.days_left })})
        </div>
      )}

      {reward && (
        <div className="note reward-applied" role="status">
          <span>🎁 {fill(t.rwApplied, { label: prizeLabel(t, reward) })} · {countdown(t, reward.expires_at, Date.now() / 1000)}</span>
          <button type="button" className="link" onClick={() => setReward(null)}>{t.rwRemove}</button>
        </div>
      )}

      {packages === null && !loadError && <div className="loader" role="status" aria-label={t.loading} />}

      {loadError && (
        <div className="banner-error" role="alert">
          {t.plansLoadErr}{' '}
          <button type="button" className="link" onClick={load}>{t.reload}</button>
        </div>
      )}

      {packages && packages.length === 0 && <p className="note">{t.noPlans}</p>}

      {packages && packages.length > 0 && (
        <div className="plans">
          {packages.map((p) => (
            <article className="plan" key={p.id}>
              <div className="plan-head">
                <h2 className="plan-name">{name(p)}</h2>
                <div className="plan-price" dir="ltr">
                  {discounted(p.price_usd) !== p.price_usd && <s className="muted">${price(p.price_usd)}</s>}{' '}
                  <strong>${price(discounted(p.price_usd))}</strong>
                </div>
              </div>
              <div className="plan-meta">{fill(t.perDays, { n: p.duration_days })}</div>
              <div className="plan-actions">
                <button type="button" className="btn primary" disabled={!!busy} onClick={() => payCrypto(p)}>
                  <img className="btn-img" src={coinIcon} alt="" />
                  <span>{busy === `${p.id}:crypto` ? t.sending : t.payCrypto}</span>
                </button>
                {tonEnabled && p.price_ton ? (
                  <button type="button" className="btn soft" disabled={!!busy} onClick={() => payTon(p)}>
                    <img className="btn-img" src={walletIcon} alt="" />
                    <span>{busy === `${p.id}:ton` ? t.sending : fill(t.payTon, { n: price(discounted(p.price_ton)) })}</span>
                  </button>
                ) : null}
                {p.price_stars ? (
                  <button type="button" className="btn soft" disabled={!!busy} onClick={() => payStars(p)}>
                    <span>{busy === `${p.id}:stars` ? t.sending : fill(t.payStars, { n: price(discounted(p.price_stars, true)) })}</span>
                  </button>
                ) : null}
              </div>
            </article>
          ))}
        </div>
      )}

      {msg && <p className="banner-error" role="alert">{t[msg]}</p>}

      <div className="actions">
        <button type="button" className="btn ghost" onClick={onBack}>
          <svg className="chev" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M15 6l-6 6 6 6" /></svg>
          <span>{t.back}</span>
        </button>
        {mode === 'flow' && sub?.active && (
          <button type="button" className="btn primary" onClick={onContinue}>
            <span>{t.next}</span>
          </button>
        )}
      </div>
    </section>
  );
}
