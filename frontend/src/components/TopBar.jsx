import React from 'react';
import logo from '../assets/logo-wordmark.png';
import Icon from './Icon';
import { haptic } from '../telegram';
import { openSupport } from '../support';
import { useTheme } from '../theme';
import { useDesign } from '../design';

/** الشريط العلوي الثابت: الشعار يسارًا دائمًا، وعلى الجهة المقابلة سماعة الدعم والإشعارات. */
export default function TopBar({ t, showBell, unread = 0, onBell }) {
  const [, setPref, theme] = useTheme();
  const tb = useDesign().pages?.topbar || {};
  return (
    <header className="app-bar top-bar" dir="ltr">
      <img src={logo} alt="AW Robot" style={tb.logo_size ? { height: tb.logo_size } : undefined} />
      <div className="top-actions">
        {tb.theme_toggle !== false && <button
          type="button"
          className="top-btn"
          aria-label={t.themeToggle}
          title={t.themeToggle}
          onClick={() => {
            haptic.select();
            setPref(theme === 'dark' ? 'light' : 'dark');
          }}
        >
          <Icon name={theme === 'dark' ? 'sun' : 'moon'} size={20} />
        </button>}
        {tb.support !== false && <button
          type="button"
          className="top-btn"
          aria-label={t.supportOpen}
          title={t.supportOpen}
          onClick={() => {
            haptic.select();
            openSupport();
          }}
        >
          <Icon name="headset" size={21} />
        </button>}
        {showBell && tb.bell !== false && (
          <button type="button" className="top-btn" aria-label={t.notifTitle} title={t.notifTitle} onClick={onBell}>
            <Icon name="bell" size={21} />
            {unread > 0 && <span className="top-badge" dir="ltr">{unread > 9 ? '9+' : unread}</span>}
          </button>
        )}
      </div>
    </header>
  );
}
