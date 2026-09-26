import React from 'react';
import { haptic } from '../telegram';
import Icon from './Icon';
import { useDesign } from '../design';

const ITEMS = [
  { view: 'main', label: 'navHome', icon: 'home' },
  { view: 'analytics', label: 'navAnalytics', icon: 'analytics' },
  { view: 'referral', label: 'navReferral', icon: 'referral' },
  { view: 'rewards', label: 'navRewards', icon: 'rewards' },
  { view: 'plans', label: 'navPlans', icon: 'plans' },
  { view: 'settings', label: 'navSettings', icon: 'settings' },
];

const LABELS = Object.fromEntries(ITEMS.map((i) => [i.view, i.label]));

// شريط تنقل سفلي ثابت: ترتيب العناصر وإظهارها وأيقوناتها ونصوصها من استوديو التصميم
export default function BottomNav({ t, lang, view, onSelect }) {
  const nav = useDesign().pages?.nav;
  const items = (nav?.items?.length ? nav.items : ITEMS.map((i) => ({ id: i.view, icon: i.icon, visible: true })))
    .filter((i) => i.visible !== false && LABELS[i.id])
    .map((i) => ({ view: i.id, icon: i.icon, text: i[`label_${lang}`] || t[LABELS[i.id]] }));
  return (
    <nav className={`bottom-nav ${nav?.labels === false ? 'no-labels' : ''}`} role="navigation">
      {items.map((item) => (
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
          <span className="bn-label">{item.text}</span>
        </button>
      ))}
    </nav>
  );
}
