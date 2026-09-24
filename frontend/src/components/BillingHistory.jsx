import React, { useEffect, useState } from 'react';
import { getBillingHistory } from '../api';
import { amount, fmtDate } from '../format';

const STATUS_LABEL = {
  finished: { ar: 'مكتمل', en: 'Finished' },
  waiting: { ar: 'قيد الانتظار', en: 'Waiting' },
  failed: { ar: 'فشل', en: 'Failed' },
  expired: { ar: 'منتهي', en: 'Expired' },
};



export default function BillingHistory({ t, lang, onBack }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    getBillingHistory()
      .then((r) => setRows(r.payments || []))
      .catch(() => setError(true));
  }, []);

  return (
    <section className="dash">
      <div className="settings-head">
        <button type="button" className="btn ghost" onClick={onBack}>
          <svg className="chev" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M15 6l-6 6 6 6" /></svg>
          <span>{t.back}</span>
        </button>
        <h1>{t.billTitle}</h1>
      </div>

      <div className="section">
        {error && <p className="note warn">{t.billError}</p>}
        {!error && rows === null && <p className="sub">{t.loading}</p>}
        {!error && rows && rows.length === 0 && <p className="sub">{t.billEmpty}</p>}

        {!error && rows && rows.length > 0 && (
          <ul className="bill-list">
            {rows.map((row) => (
              <li key={row.order_id} className="bill-item">
                <div className="bill-top">
                  <strong className="bill-plan">{(lang === 'ar' ? row.plan_name_ar : row.plan_name_en) || '—'}</strong>
                  <span className="bill-amount" dir="ltr">{row.currency === 'USD' ? `$${amount(row.amount)}` : `${amount(row.amount)} ${row.currency === 'XTR' ? '⭐' : row.currency}`}</span>
                </div>
                <div className="bill-meta">
                  <span>{fmtDate(row.date, lang)}</span>
                  <span className={`bill-status bill-${row.status}`}>{STATUS_LABEL[row.status]?.[lang] || row.status}</span>
                </div>
                <div className="bill-tx">
                  <span className="muted">{t.billTx}</span>
                  <code dir="ltr">{row.tx_id}</code>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
