import React, { useEffect, useState } from 'react';
import { getBillingHistory } from '../api';

const STATUS_LABEL = {
  finished: { ar: 'مكتمل', en: 'Finished' },
  waiting: { ar: 'قيد الانتظار', en: 'Waiting' },
  failed: { ar: 'فشل', en: 'Failed' },
  expired: { ar: 'منتهي', en: 'Expired' },
};

function fmtDate(ts, lang) {
  if (!ts) return '—';
  return new Date(ts * 1000).toLocaleDateString(lang === 'ar' ? 'ar' : 'en-GB', { year: 'numeric', month: 'short', day: 'numeric' });
}

function downloadReceipt(row, t, lang) {
  const plan = (lang === 'ar' ? row.plan_name_ar : row.plan_name_en) || row.plan_name_en || row.plan_name_ar || '—';
  const status = STATUS_LABEL[row.status]?.[lang] || row.status;
  const lines = [
    'AW Robot',
    '——————————————',
    `${t.billDate}: ${fmtDate(row.date, lang)}`,
    `${t.billPlan}: ${plan}`,
    `${t.billAmount}: ${row.amount ?? '—'} ${row.currency === 'XTR' ? '⭐' : row.currency}`,
    `${t.billStatus}: ${status}`,
    `${t.billTx}: ${row.tx_id}`,
  ];
  const blob = new Blob([lines.join('\n')], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `AW-Robot-receipt-${row.order_id}.txt`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

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
          <div className="bill-table-wrap">
            <table className="bill-table">
              <thead>
                <tr>
                  <th>{t.billDate}</th>
                  <th>{t.billPlan}</th>
                  <th>{t.billAmount}</th>
                  <th>{t.billStatus}</th>
                  <th aria-hidden="true" />
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.order_id}>
                    <td>{fmtDate(row.date, lang)}</td>
                    <td>{(lang === 'ar' ? row.plan_name_ar : row.plan_name_en) || '—'}</td>
                    <td dir="ltr">{row.amount ?? '—'} {row.currency === 'XTR' ? '⭐' : row.currency}</td>
                    <td>
                      <span className={`bill-status bill-${row.status}`}>{STATUS_LABEL[row.status]?.[lang] || row.status}</span>
                    </td>
                    <td>
                      <button type="button" className="btn soft small" onClick={() => downloadReceipt(row, t, lang)}>
                        <span>{t.billDownload}</span>
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}
