import React from 'react';
import { haptic } from '../telegram';

const ITEMS = [
  { view: 'main', label: 'navHome', icon: '🏠' },
  { view: 'plans', label: 'navPlans', icon: '💎' },
  { view: 'settings', label: 'navSettings', icon: '⚙️' },
];

// شريط تنقل سفلي ثابت بين اللوحة الرئيسية والباقات والإعدادات.
export default function BottomNav({ t, view, onSelect }) {
  return (
    <nav className="bottom-nav" role="navigation">
      {ITEMS.map((item) => (
        <button
          key={item.view}
          type="button"
          className={`bn-item ${view === item.view ? 'on' : ''}`}
          onClick={() => {
            haptic.select();
            onSelect(item.view);
          }}
        >
          <span className="bn-icon">{item.icon}</span>
          <span className="bn-label">{t[item.label]}</span>
        </button>
      ))}
    </nav>
  );
}
