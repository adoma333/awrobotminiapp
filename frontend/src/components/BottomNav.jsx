import React from 'react';
import { haptic } from '../telegram';
import Icon from './Icon';

const ITEMS = [
  { view: 'main', label: 'navHome', icon: 'home' },
  { view: 'analytics', label: 'navAnalytics', icon: 'analytics' },
  { view: 'referral', label: 'navReferral', icon: 'referral' },
  { view: 'rewards', label: 'navRewards', icon: 'rewards' },
  { view: 'plans', label: 'navPlans', icon: 'plans' },
  { view: 'settings', label: 'navSettings', icon: 'settings' },
];

// شريط تنقل سفلي ثابت بأيقونات خطية موحّدة.
export default function BottomNav({ t, view, onSelect }) {
  return (
    <nav className="bottom-nav" role="navigation">
      {ITEMS.map((item) => (
        <button
          key={item.view}
          type="button"
          className={`bn-item ${view === item.view ? 'on' : ''}`}
          aria-current={view === item.view ? 'page' : undefined}
          onClick={() => {
            haptic.select();
            onSelect(item.view);
          }}
        >
          <Icon name={item.icon} size={21} className="bn-icon" />
          <span className="bn-label">{t[item.label]}</span>
        </button>
      ))}
    </nav>
  );
}
