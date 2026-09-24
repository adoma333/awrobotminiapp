import React from 'react';

export { fmt, pct, tone, timeAgo } from '../format';

export function Row({ label, value, kind, hint, plain }) {
  return (
    <div className="row">
      <span className="row-label">
        {label}
        {hint && <small>{hint}</small>}
      </span>
      <span className={`row-value ${kind || ''}`} dir={plain ? undefined : 'ltr'}>
        {value}
      </span>
    </div>
  );
}

