import React from 'react';

function Emblem({ status }) {
  return (
    <svg className={`emblem is-${status}`} viewBox="0 0 96 96" width="96" height="96" aria-hidden="true">
      <defs>
        <linearGradient id="em-grad" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#FF8A00" />
          <stop offset="1" stopColor="#FF5A00" />
        </linearGradient>
      </defs>

      {status === 'pending' && (
        <>
          <circle cx="48" cy="48" r="38" fill="none" stroke="rgba(255,138,0,.18)" strokeWidth="3" />
          <circle
            className="spin"
            cx="48" cy="48" r="38" fill="none"
            stroke="url(#em-grad)" strokeWidth="3" strokeLinecap="round"
            strokeDasharray="70 170"
          />
          <circle cx="48" cy="48" r="5" fill="url(#em-grad)" />
        </>
      )}

      {status === 'approved' && (
        <>
          <circle cx="48" cy="48" r="38" fill="none" stroke="#3DDC97" strokeWidth="3" />
          <path d="M31 49l12 12 22-25" fill="none" stroke="#3DDC97" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" />
        </>
      )}

      {status === 'rejected' && (
        <>
          <circle cx="48" cy="48" r="38" fill="none" stroke="#FF6B5E" strokeWidth="3" />
          <path d="M35 35l26 26M61 35L35 61" fill="none" stroke="#FF6B5E" strokeWidth="5" strokeLinecap="round" />
        </>
      )}
    </svg>
  );
}

export default function StatusScreen({ t, status, reason, onRetry, onClose }) {
  const title = t[`${status}Title`];
  const body = t[`${status}Body`];

  return (
    <section className="step status" aria-live="polite">
      <Emblem status={status} />
      <h1>{title}</h1>
      {body && <p className="sub">{body}</p>}

      {status === 'rejected' && reason && (
        <div className="reason">
          <span className="label">{t.reason}</span>
          <p dir="auto">{reason}</p>
        </div>
      )}

      <div className="actions">
        {status === 'rejected' && (
          <button type="button" className="btn primary" onClick={onRetry}>
            <span>{t.retry}</span>
          </button>
        )}
        {status === 'approved' && (
          <button type="button" className="btn primary" onClick={onClose}>
            <span>{t.close}</span>
          </button>
        )}
      </div>
    </section>
  );
}
