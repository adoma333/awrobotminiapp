import React from 'react';
import { haptic } from '../telegram';
import Icon from './Icon';
import { blocksOf, useDesign } from '../design';

const LANGS = [
  { code: 'ar', name: 'العربية' },
  { code: 'en', name: 'English' },
];

// صفحة البداية: ترتيب العناصر وإظهارها ونصوص الميزات وأيقوناتها من استوديو التصميم
export default function LanguageStep({ t, lang, setLang, onNext }) {
  const d = useDesign();
  const perks = (d.pages?.start?.perks || []).map((p, i) => ({ icon: p.icon, text: p[`text_${lang}`] || t[`perk${i + 1}`] || '' })).filter((p) => p.text);
  const parts = {
    title: <h1 key="title">{t.langTitle}</h1>,
    options: (
      <div key="options" className="options" role="radiogroup" aria-label={t.langTitle}>
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
    ),
    perks: perks.length > 0 && (
      <ul key="perks" className="lang-perks" aria-label="AW">
        {perks.map((p) => (
          <li key={p.text}><span aria-hidden="true"><Icon name={p.icon} size={18} /></span>{p.text}</li>
        ))}
      </ul>
    ),
  };
  return (
    <section className="step lang-step">
      <div className="lang-body">{blocksOf('start').map((id) => parts[id] || null)}</div>
      <div className="actions">
        <button type="button" className="btn primary" onClick={onNext}>
          <span>{t.next}</span>
        </button>
      </div>
    </section>
  );
}
