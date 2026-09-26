import React from 'react';
import { haptic } from '../telegram';

const LANGS = [
  { code: 'ar', name: 'العربية' },
  { code: 'en', name: 'English' },
];

export default function LanguageStep({ t, lang, setLang, onNext }) {
  return (
    <section className="step lang-step">
      <div className="lang-body">
      <h1>{t.langTitle}</h1>

      <div className="options" role="radiogroup" aria-label={t.langTitle}>
        {LANGS.map((l) => (
          <button
            key={l.code}
            type="button"
            role="radio"
            aria-checked={lang === l.code}
            className={`option ${lang === l.code ? 'is-selected' : ''}`}
            onClick={() => {
              haptic.select();
              setLang(l.code);
            }}
          >
            <span className={`option-name ${l.code === 'ar' ? 'is-ar' : ''}`} lang={l.code}>
              {l.name}
            </span>
            <span className="ring" />
          </button>
        ))}
      </div>

      <ul className="lang-perks" aria-label="AW">
        {[['⚡', t.perk1], ['📊', t.perk2], ['🔒', t.perk3]].map(([ic, label]) => (
          <li key={label}><span aria-hidden="true">{ic}</span>{label}</li>
        ))}
      </ul>
      </div>

      <div className="actions">
        <button type="button" className="btn primary" onClick={onNext}>
          <span>{t.next}</span>
        </button>
      </div>
    </section>
  );
}
