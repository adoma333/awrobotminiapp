import React, { useEffect, useState } from 'react';
import PageHead from './PageHead';
import ErrorNote from './ErrorNote';
import { getBillingHistory } from '../api';
import { amount, fmtDate } from '../format';
import starsIcon from '../assets/icons/stars.webp';

const STATUS_LABEL = {
  finished: { ar: 'مكتمل', en: 'Finished' },
  waiting: { ar: 'قيد الانتظار', en: 'Waiting' },
  failed: { ar: 'فشل', en: 'Failed' },
  expired: { ar: 'منتهي', en: 'Expired' },
  partially_paid: { ar: 'مدفوع جزئيًا', en: 'Partially paid' },
  underpaid: { ar: 'ناقص — قيد المراجعة', en: 'Underpaid — under review' },
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
      <PageHead t={t} title={t.billTitle} onBack={onBack} />

      <div className="section">
        {error && <ErrorNote t={t} kind="operation" code="billing_load_failed">{t.billError}</ErrorNote>}
        {!error && rows === null && <p className="sub">{t.loading}</p>}
        {!error && rows && rows.length === 0 && <p className="sub">{t.billEmpty}</p>}

        {!error && rows && rows.length > 0 && (
          <ul className="bill-list">
            {rows.map((row) => (
              <li key={row.order_id} className="bill-item">
                <div className="bill-top">
                  <strong className="bill-plan">{(lang === 'ar' ? row.plan_name_ar : row.plan_name_en) || '—'}</strong>
                  <span className="bill-amount" dir="ltr">{row.currency === 'USD' ? `$${amount(row.amount)}` : row.currency === 'XTR' ? <>{amount(row.amount)} <img src={starsIcon} alt="Stars" className="cur-ic" /></> : `${amount(row.amount)} ${row.currency}`}</span>
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
