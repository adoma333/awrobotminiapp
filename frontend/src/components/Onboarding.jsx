import React, { useState } from 'react';
import { haptic } from '../telegram';

const ICONS = ['📈', '🔒', '💬'];

// شاشات شرح تعريفي قصيرة تظهر مرة واحدة فقط لكل مستخدم جديد.
export default function Onboarding({ t, onDone }) {
  const [i, setI] = useState(0);
  const slides = [
    { title: t.ob1Title, body: t.ob1Body },
    { title: t.ob2Title, body: t.ob2Body },
    { title: t.ob3Title, body: t.ob3Body },
  ];
  const last = i === slides.length - 1;

  const next = () => {
    haptic.select();
    if (last) onDone();
    else setI((n) => n + 1);
  };

  return (
    <section className="step onboarding" aria-live="polite">
      <div className="ob-icon">{ICONS[i]}</div>
      <h1>{slides[i].title}</h1>
      <p className="sub">{slides[i].body}</p>
      <div className="ob-dots">
        {slides.map((_, idx) => (
          <span key={idx} className={`ob-dot ${idx === i ? 'on' : ''}`} />
        ))}
      </div>
      <div className="ob-actions">
        {!last && (
          <button type="button" className="btn ghost" onClick={onDone}>
            <span>{t.obSkip}</span>
          </button>
        )}
        <button type="button" className="btn primary" onClick={next}>
          <span>{last ? t.obStart : t.obNext}</span>
        </button>
      </div>
    </section>
  );
}
