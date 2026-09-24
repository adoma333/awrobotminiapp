import React, { useEffect, useState } from 'react';
import Field from './Field';
import { LOGIN_RE } from '../i18n';

function Verifying({ t, secs }) {
  const line = secs < 8 ? t.verify1 : secs < 35 ? t.verify2 : t.verify3;
  return (
    <section className="step status" aria-live="polite">
      <svg className="emblem is-pending" viewBox="0 0 96 96" width="96" height="96" aria-hidden="true">
        <defs>
          <linearGradient id="vf-grad" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#FF8A00" />
            <stop offset="1" stopColor="#FF5A00" />
          </linearGradient>
        </defs>
        <circle cx="48" cy="48" r="38" fill="none" stroke="rgba(255,138,0,.18)" strokeWidth="3" />
        <circle className="spin" cx="48" cy="48" r="38" fill="none" stroke="url(#vf-grad)" strokeWidth="3" strokeLinecap="round" strokeDasharray="70 170" />
        <circle cx="48" cy="48" r="5" fill="url(#vf-grad)" />
      </svg>
      <h1>{t.verifyTitle}</h1>
      <p className="sub">{line}</p>
      <p className="muted">{t.verifyNote}</p>
    </section>
  );
}

export default function MT5FormStep({ t, mt5, setMt5, submitting, errorCode, onSubmit, onBack, termsOk, setTermsOk, onOpenTerms }) {
  const [secs, setSecs] = useState(0);
  useEffect(() => {
    if (!submitting) {
      setSecs(0);
      return undefined;
    }
    const id = setInterval(() => setSecs((s) => s + 1), 1000);
    return () => clearInterval(id);
  }, [submitting]);

  if (submitting) return <Verifying t={t} secs={secs} />;

  const loginInvalid = mt5.login !== '' && !LOGIN_RE.test(mt5.login);
  const valid = LOGIN_RE.test(mt5.login) && mt5.password.length > 0 && mt5.server.trim().length >= 2 && termsOk;

  return (
    <section className="step">
      <h1>{t.mt5Title}</h1>
      <p className="sub">{t.mt5Sub}</p>

      <Field
        label={t.login}
        placeholder={t.loginPh}
        value={mt5.login}
        inputMode="numeric"
        maxLength={12}
        error={loginInvalid ? t.errLogin : ''}
        onChange={(v) => setMt5({ ...mt5, login: v.replace(/\s/g, '') })}
        autoFocus
      />
      <Field
        label={t.password}
        type="password"
        value={mt5.password}
        toggleLabels={{ show: t.showPassword, hide: t.hidePassword }}
        onChange={(v) => setMt5({ ...mt5, password: v })}
      />
      <Field
        label={t.server}
        placeholder={t.serverPh}
        value={mt5.server}
        onChange={(v) => setMt5({ ...mt5, server: v })}
      />

      <div className={`consent ${termsOk ? 'is-on' : ''}`}>
        <label className="consent-check">
          <input type="checkbox" checked={termsOk} onChange={(e) => setTermsOk(e.target.checked)} />
          <span>{t.termsConsent}</span>
        </label>
        <button type="button" className="consent-link" onClick={onOpenTerms}>
          Terms &amp; Risks
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M9 6l6 6-6 6" /></svg>
        </button>
      </div>

      {errorCode && (
        <p className="banner-error" role="alert">
          {t[`err_${errorCode}`] || t.errGeneric}
        </p>
      )}

      <div className="actions">
        {onBack && (
          <button type="button" className="btn ghost" onClick={onBack}>
            <svg className="chev" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M15 6l-6 6 6 6" /></svg>
            <span>{t.back}</span>
          </button>
        )}
        <button type="button" className="btn primary" disabled={!valid} onClick={onSubmit}>
          <span>{t.submit}</span>
        </button>
      </div>
    </section>
  );
}
