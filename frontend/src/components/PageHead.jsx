import React from 'react';

/** رأس موحّد لكل الصفحات الداخلية: زر الرجوع ثابت دائمًا في الموضع نفسه (أعلى الشاشة، جهة البداية). */
export default function PageHead({ t, title, onBack, children }) {
  return (
    <div className="page-head">
      <button type="button" className="page-back" onClick={onBack} aria-label={t.back}>
        <svg className="chev" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M15 6l-6 6 6 6" /></svg>
        <span>{t.back}</span>
      </button>
      {title && <h1>{title}</h1>}
      {children}
    </div>
  );
}
