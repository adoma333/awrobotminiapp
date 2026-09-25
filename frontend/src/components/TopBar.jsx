import React from 'react';
import logo from '../assets/logo-wordmark.png';
import Icon from './Icon';
import { haptic } from '../telegram';
import { openSupport } from '../support';

/** الشريط العلوي الثابت: الشعار يسارًا دائمًا، وعلى الجهة المقابلة سماعة الدعم والإشعارات. */
export default function TopBar({ t, showBell, unread = 0, onBell }) {
  return (
    <header className="app-bar top-bar" dir="ltr">
      <img src={logo} alt="AW Robot" />
      <div className="top-actions">
        <button
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
        </button>
        {showBell && (
          <button type="button" className="top-btn" aria-label={t.notifTitle} title={t.notifTitle} onClick={onBell}>
            <Icon name="bell" size={21} />
            {unread > 0 && <span className="top-badge" dir="ltr">{unread > 9 ? '9+' : unread}</span>}
          </button>
        )}
      </div>
    </header>
  );
}
