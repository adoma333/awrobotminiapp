import React, { useEffect, useState } from 'react';
import QRCode from 'qrcode';
import logo from '../assets/logo-wordmark.png';
import Icon from './Icon';
import { useDesign } from '../design';

/**
 * يظهر لمن يفتح رابط التطبيق من متصفح (Chrome, Safari…) خارج تلجرام: التطبيق يعمل داخل تلجرام فقط.
 * رمز QR لفتحه من الهاتف + زر يفتح البوت مباشرة. نصوصه وخياراته من استوديو التصميم.
 */
export default function OutsideTelegram({ t, lang, setLang }) {
  const d = useDesign();
  const L = d.pages?.landing || {};
  const bot = d.bot || '';
  const link = bot ? `https://t.me/${bot}?start=web` : 'https://t.me';
  const [qr, setQr] = useState('');
  const pick = (k) => L[`${k}_${lang}`] || L[`${k}_${lang === 'ar' ? 'en' : 'ar'}`] || '';

  useEffect(() => {
    if (L.show_qr === false) return;
    const cs = getComputedStyle(document.documentElement);
    QRCode.toDataURL(link, { width: 520, margin: 1, errorCorrectionLevel: 'M',
      color: { dark: cs.getPropertyValue('--bone').trim() || '#f5efe8', light: '#00000000' } })
      .then(setQr).catch(() => setQr(''));
  }, [link, L.show_qr, d]);

  return (
    <main className="app landing" dir={t.dir}>
      <div className="landing-top">
        <img className="landing-logo" src={logo} alt="AW ROBOT" />
        <button type="button" className="landing-lang" onClick={() => setLang(lang === 'ar' ? 'en' : 'ar')}>{lang === 'ar' ? 'EN' : 'ع'}</button>
      </div>
      <section className="landing-body">
        <span className="landing-badge"><Icon name="telegram" size={16} /> Telegram Mini App</span>
        <h1>{pick('title')}</h1>
        <p className="sub">{pick('sub')}</p>
        {L.show_qr !== false && qr && (
          <div className="landing-qr">
            <img src={qr} alt="QR" />
            <span className="landing-qr-ic"><Icon name="telegram" size={26} /></span>
          </div>
        )}
        <a className="btn primary landing-cta" href={link} rel="noopener"><span>{pick('button')}</span></a>
        <p className="landing-link" dir="ltr">{link.replace('https://', '')}</p>
        {L.show_features !== false && (
          <ul className="lang-perks">
            {[['⚡', t.perk1], ['📊', t.perk2], ['🔒', t.perk3]].map(([ic, label]) => (
              <li key={label}><span aria-hidden="true">{ic}</span>{label}</li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
