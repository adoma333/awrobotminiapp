import React from 'react';

// أفاتار هندسي بلون الشعار (فتى / فتاة)
export default function Avatar({ kind = 'boy', size = 64 }) {
  const grad = `av-grad-${kind}`;
  const clip = `av-clip-${kind}`;
  const hair = '#A63C00';

  return (
    <svg viewBox="0 0 64 64" width={size} height={size} aria-hidden="true">
      <defs>
        <linearGradient id={grad} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#FF8A00" />
          <stop offset="1" stopColor="#FF5A00" />
        </linearGradient>
        <clipPath id={clip}>
          <circle cx="32" cy="32" r="30" />
        </clipPath>
      </defs>

      <circle cx="32" cy="32" r="30" fill="#0d0703" />

      <g clipPath={`url(#${clip})`}>
        {/* الكتفان */}
        <path
          d="M8 66 C8 51 19 45 32 45 C45 45 56 51 56 66 Z"
          fill={`url(#${grad})`}
        />

        {/* شعر الفتاة الطويل خلف الرأس */}
        {kind === 'girl' && (
          <path
            d="M32 10.5 C40 10.5 46.5 15.5 46 29 C45.8 37 47.5 44 49.5 50 L41.5 50 C41 46 40.5 42 40 38 L24 38 C23.5 42 23 46 22.5 50 L14.5 50 C16.5 44 18.2 37 18 29 C17.5 15.5 24 10.5 32 10.5 Z"
            fill={hair}
          />
        )}

        {/* الرقبة والرأس */}
        <rect x="27.5" y="35" width="9" height="12" rx="3" fill={`url(#${grad})`} />
        <circle cx="32" cy="28" r="10.5" fill={`url(#${grad})`} />

        {/* الشعر العلوي */}
        {kind === 'boy' ? (
          <path
            d="M21 26.5 C19.5 15 26.5 11.5 32 11.5 C37.5 11.5 44.5 15 43 26.5 C41.5 21.8 37.5 20 32 20 C26.5 20 22.5 21.8 21 26.5 Z"
            fill={hair}
          />
        ) : (
          <path
            d="M21.3 27.5 C20.5 17 26.5 15 32 15 C37.5 15 43.5 17 42.7 27.5 C40.5 23 36.5 20 31.5 20.2 C27 20.5 23.5 23 21.3 27.5 Z"
            fill={hair}
          />
        )}
      </g>

      <circle
        cx="32"
        cy="32"
        r="30"
        fill="none"
        stroke={`url(#${grad})`}
        strokeWidth="2"
      />
    </svg>
  );
}
