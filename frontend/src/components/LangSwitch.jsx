import React from 'react';
import { haptic } from '../telegram';

const LANGS = [
  { code: 'ar', label: 'العربية', short: 'ع' },
  { code: 'en', label: 'English', short: 'EN' },
];

/** مبدّل لغة احترافي: تبديل فوري بلا إعادة تحميل، مؤشر منزلق متحرك بنفس هوية البوت. */
export default function LangSwitch({ lang, onChange, label }) {
  const idx = Math.max(0, LANGS.findIndex((l) => l.code === lang));
  return (
    <div className="lang-switch" role="radiogroup" aria-label={label} dir="ltr" style={{ '--i': idx }}>
      <span className="lang-thumb" aria-hidden="true" />
      {LANGS.map((l) => (
        <button
          key={l.code}
          type="button"
          role="radio"
          aria-checked={lang === l.code}
          className={`lang-opt ${lang === l.code ? 'is-on' : ''}`}
          lang={l.code}
          onClick={() => {
            if (l.code === lang) return;
            haptic.select();
            onChange(l.code);
          }}
        >
          <span className="lang-short">{l.short}</span>
          <span className="lang-label">{l.label}</span>
        </button>
      ))}
    </div>
  );
}
