import React, { useCallback, useEffect, useState } from 'react';
import { createPayment, createStarsPayment, getPackages } from '../api';
import { fill } from '../i18n';
import { haptic, openExternal, openInvoice } from '../telegram';

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
export default function Plans({ t, lang, sub, refreshStatus, mode, onContinue, onBack }) {
  const [packages, setPackages] = useState(null);
  const [loadError, setLoadError] = useState(false);
  const [busy, setBusy] = useState('');
  const [msg, setMsg] = useState('');
  const [waiting, setWaiting] = useState(null); // { startExpiry }
  const [paid, setPaid] = useState(false);

  const load = useCallback(() => {
    setLoadError(false);
    setPackages(null);
    getPackages()
      .then((r) => setPackages(r.packages || []))
      .catch(() => setLoadError(true));
  }, []);
  useEffect(load, [load]);

  // يفحص تفعيل الاشتراك: ظهور تاريخ انتهاء أبعد من وقت بدء الدفع
  const check = useCallback(async () => {
    if (!waiting) return;
    try {
      const s = await refreshStatus();
      const sb = s.subscription;
      if (sb?.active && sb.expires_at > waiting.startExpiry + 60) {
        setWaiting(null);
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

  const startWaiting = () => setWaiting({ startExpiry: sub?.expires_at || 0 });

  async function payCrypto(pkg) {
    setBusy(`${pkg.id}:crypto`);
    setMsg('');
    try {
      const r = await createPayment(pkg.id);
      openExternal(r.invoice_url);
      startWaiting();
    } catch (e) {
      haptic.error();
      setMsg(e.detail === 'payment_provider_error' ? 'payProviderErr' : 'payErr');
    } finally {
      setBusy('');
    }
  }

  async function payStars(pkg) {
    setBusy(`${pkg.id}:stars`);
    setMsg('');
    try {
      const r = await createStarsPayment(pkg.id);
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
      setMsg(e.detail === 'stars_not_configured_for_package' ? 'starsNotReady' : 'payErr');
    } finally {
      setBusy('');
    }
  }

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
                  <strong>${price(p.price_usd)}</strong>
                </div>
              </div>
              <div className="plan-meta">{fill(t.perDays, { n: p.duration_days })}</div>
              <div className="plan-actions">
                <button type="button" className="btn primary" disabled={!!busy} onClick={() => payCrypto(p)}>
                  <span>{busy === `${p.id}:crypto` ? t.sending : t.payCrypto}</span>
                </button>
                {p.price_stars ? (
                  <button type="button" className="btn soft" disabled={!!busy} onClick={() => payStars(p)}>
                    <span>{busy === `${p.id}:stars` ? t.sending : fill(t.payStars, { n: price(p.price_stars) })}</span>
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
