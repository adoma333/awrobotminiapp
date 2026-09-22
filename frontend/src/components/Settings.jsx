import React, { useState } from 'react';
import { unlink, updateProfile, errorCodeOf } from '../api';
import { fill } from '../i18n';
import { copyText, haptic, openTelegramLink } from '../telegram';

const LANGS = [
  { code: 'ar', name: 'العربية' },
  { code: 'en', name: 'English' },
];

const fmtDate = (epoch, lang) =>
  epoch
    ? new Date(epoch * 1000).toLocaleDateString(lang === 'ar' ? 'ar-u-nu-latn' : 'en', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
      })
    : '—';

export default function Settings({ t, lang, setLang, data, onBack, onRenew, onUnlinked, onLegal, onFaq, onCalc }) {
  const sub = data.subscription;
  const cfg = data.settings || {};
  const code = data.referral_code;
  const link = code && data.bot_username ? `https://t.me/${data.bot_username}?start=${code}` : null;

  const [copied, setCopied] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  function pickLang(l) {
    haptic.select();
    setLang(l);
    updateProfile({ language: l }).catch(() => {}); // كي تصلك الإشعارات بلغتك
  }

  async function doCopy() {
    const ok = await copyText(link || code);
    if (ok) {
      haptic.success();
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }

  function doShare() {
    if (!link) return;
    openTelegramLink(`https://t.me/share/url?url=${encodeURIComponent(link)}&text=${encodeURIComponent(t.shareText)}`);
  }

  async function doUnlink() {
    setBusy(true);
    setError('');
    try {
      await unlink();
      haptic.success();
      await onUnlinked();
    } catch (e) {
      haptic.error();
      const c = errorCodeOf(e);
      const m = /^cooldown_(\d+)h$/.exec(c);
      if (m) setError(fill(t.unlinkCooldown, { n: m[1] }));
      else if (c === 'not_linked') await onUnlinked();
      else setError(t.unlinkErr);
      setConfirm(false);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="dash">
      <div className="settings-head">
        <button type="button" className="btn ghost" onClick={onBack}>
          <svg className="chev" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M15 6l-6 6 6 6" /></svg>
          <span>{t.back}</span>
        </button>
        <h1>{t.settingsTitle}</h1>
      </div>

      <div className="section">
        <h2>{t.language}</h2>
        <div className="options" role="radiogroup" aria-label={t.language}>
          {LANGS.map((l) => (
            <button
              key={l.code}
              type="button"
              role="radio"
              aria-checked={lang === l.code}
              className={`option ${lang === l.code ? 'is-selected' : ''}`}
              onClick={() => pickLang(l.code)}
            >
              <span className={`option-name ${l.code === 'ar' ? 'is-ar' : ''}`} lang={l.code}>{l.name}</span>
              <span className="ring" />
            </button>
          ))}
        </div>
      </div>

      <div className="section">
        <h2>{t.plan}</h2>
        <div className="rows">
          <div className="row">
            <span className="row-label">{t.currentPlan}</span>
            <span className="row-value">
              {sub ? (lang === 'ar' ? sub.package_name_ar : sub.package_name_en) || '—' : '—'}
            </span>
          </div>
          <div className="row">
            <span className="row-label">{sub?.active ? fill(t.expiresOn, { date: '' }).trim() : t.subExpired}</span>
            <span className="row-value">
              {sub ? `${fmtDate(sub.expires_at, lang)}${sub.active ? ` (${fill(t.daysLeft, { n: sub.days_left })})` : ''}` : '—'}
            </span>
          </div>
        </div>
        <div className="actions inline">
          <button type="button" className="btn soft" onClick={onRenew}>
            <span>{t.renew}</span>
          </button>
        </div>
      </div>

      {code && (
        <div className="section">
          <h2>{t.inviteTitle}</h2>
          <p className="sub">{cfg.referral_enabled ? fill(t.inviteBody, { n: cfg.referral_days ?? 7 }) : t.inviteBodyPlain}</p>
          <div className="code-box">
            <div>
              <span className="muted">{t.yourCode}</span>
              <strong dir="ltr">{code}</strong>
            </div>
            <button type="button" className="btn soft small" onClick={doCopy}>
              <span>{copied ? t.copied : t.copy}</span>
            </button>
          </div>
          {link && (
            <div className="actions inline">
              <button type="button" className="btn primary" onClick={doShare}>
                <span>{t.share}</span>
              </button>
            </div>
          )}
        </div>
      )}

      <div className="section">
        <h2>{t.faqTitle}</h2>
        <div className="rows">
          <button type="button" className="row row-link" onClick={onFaq}>
            <span className="row-label">{t.faqLink}</span>
            <svg className="chev" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M9 6l6 6-6 6" /></svg>
          </button>
          <button type="button" className="row row-link" onClick={onCalc}>
            <span className="row-label">{t.calcLink}</span>
            <svg className="chev" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M9 6l6 6-6 6" /></svg>
          </button>
        </div>
      </div>

      <div className="section">
        <h2>{t.legalTitle}</h2>
        <div className="rows">
          <button type="button" className="row row-link" onClick={() => onLegal('terms')}>
            <span className="row-label">{t.termsLink}</span>
            <svg className="chev" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M9 6l6 6-6 6" /></svg>
          </button>
          <button type="button" className="row row-link" onClick={() => onLegal('privacy')}>
            <span className="row-label">{t.privacyLink}</span>
            <svg className="chev" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M9 6l6 6-6 6" /></svg>
          </button>
        </div>
      </div>

      <div className="section danger-zone">
        <h2>{t.unlinkTitle}</h2>
        {!confirm ? (
          <>
            <p className="sub">{t.unlinkBody}</p>
            {error && <p className="banner-error" role="alert">{error}</p>}
            <div className="actions inline">
              <button type="button" className="btn danger" onClick={() => { setError(''); setConfirm(true); }}>
                <span>{t.unlinkBtn}</span>
              </button>
            </div>
          </>
        ) : (
          <>
            <p className="banner-error" role="alertdialog">{t.unlinkConfirm}</p>
            <div className="actions">
              <button type="button" className="btn ghost" disabled={busy} onClick={() => setConfirm(false)}>
                <span>{t.unlinkNo}</span>
              </button>
              <button type="button" className="btn danger" disabled={busy} onClick={doUnlink}>
                <span>{busy ? t.sending : t.unlinkYes}</span>
              </button>
            </div>
          </>
        )}
      </div>
    </section>
  );
}
