import React, { useEffect, useState } from 'react';
import Icon from './Icon';
import { haptic } from '../telegram';

/** نافذة "ما الجديد": محتواها وتوقيت ظهورها يتحكم بهما الأدمن بالكامل. */
export default function WhatsNew({ t, lang, ann, onClose }) {
  const [never, setNever] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const st = ann.style || {};
  const appTheme = st.theme === 'app'; // يتبع وضع التطبيق (ليلي/نهاري) بألوانه
  const full = st.position === 'fullscreen';
  const imgMode = ann.image ? st.image_mode || 'top' : 'none';
  // الشكل يأتي من المعاينة الحية في لوحة التحكم (ألوان، عرض، استدارة، تمويه، موضع، صورة، زر، حركة)
  const sheetStyle = {
    ...(!appTheme && st.accent && { '--ember': st.accent, '--wn-accent': st.accent }),
    ...(!appTheme && st.accent2 && { '--flame': st.accent2 }),
    ...(!appTheme && st.accent && st.accent2 && { '--grad': `linear-gradient(135deg, ${st.accent}, ${st.accent2})` }),
    ...(!appTheme && st.text && { color: st.text }),
    ...(!appTheme && st.bg && { '--wn-bg': st.bg }),
    ...(st.width && !full && { maxWidth: `${st.width}px` }),
    ...(st.radius != null && { '--wn-radius': `${full ? 0 : st.radius}px` }),
    ...(st.title_size && { '--wn-title': `${st.title_size}px` }),
    ...(imgMode === 'background' && {
      backgroundImage: `linear-gradient(rgba(0,0,0,${(st.overlay ?? 55) / 100}), rgba(0,0,0,${Math.min(0.95, (st.overlay ?? 55) / 100 + 0.2)})), url("${ann.image}")`,
      backgroundSize: 'cover', backgroundPosition: st.image_focus || 'center', ...(!appTheme && { color: st.text || '#fff' }),
    }),
  };
  const imgStyle = {
    height: `${st.image_height || 180}px`, objectFit: st.image_fit || 'cover', objectPosition: `center ${st.image_focus || 'center'}`,
    borderRadius: imgMode === 'full' ? 0 : `${st.image_radius ?? 18}px`,
  };
  const L = (k) => ann[`${k}_${lang}`] || ann[`${k}_${lang === 'ar' ? 'en' : 'ar'}`] || '';

  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && close('close');
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  function close(action) {
    haptic.select();
    setLeaving(true);
    setTimeout(() => onClose(action, never), 180);
  }

  return (
    <div
      className={`wn-backdrop ${st.position === 'center' ? 'is-center' : ''} ${full ? 'is-full' : ''} ${leaving ? 'is-leaving' : ''}`}
      style={st.blur != null ? { backdropFilter: `blur(${st.blur}px)`, WebkitBackdropFilter: `blur(${st.blur}px)` } : undefined}
      onClick={(e) => e.target === e.currentTarget && close('close')}>
      <section
        className={`wn-sheet anim-${st.animation || 'slide'} ${appTheme ? 'is-app-theme' : ''} ${st.align === 'start' ? 'is-start' : ''} ${st.cta_place === 'sticky' ? 'has-sticky' : ''} img-${imgMode}`}
        style={sheetStyle} role="dialog" aria-modal="true" aria-labelledby="wn-title">
        {st.show_close !== false && <button type="button" className="wn-x" aria-label={t.close} onClick={() => close('close')}><Icon name="close" size={18} /></button>}
        {imgMode === 'top' || imgMode === 'full' ? (
          <img className={`wn-hero-img ${imgMode === 'full' ? 'is-bleed' : ''}`} src={ann.image} alt="" style={imgStyle} />
        ) : imgMode === 'none' ? (
          <div className="wn-hero" aria-hidden="true">
            <span className="wn-orb" />
            <Icon name="bolt" size={34} />
          </div>
        ) : null}
        {L('badge') && <span className="wn-badge">{L('badge')}</span>}
        <h2 id="wn-title">{L('title')}</h2>
        {L('subtitle') && <p className="wn-sub">{L('subtitle')}</p>}
        {(ann.features || []).length > 0 && (
          <ul className="wn-features">
            {ann.features.map((f, i) => (
              <li key={i} style={{ animationDelay: `${120 + i * 70}ms` }}>
                <span className="wn-ic"><Icon name={f.icon || 'check'} size={19} /></span>
                <div>
                  <b>{f[`title_${lang}`] || f.title_en || f.title_ar}</b>
                  {(f[`text_${lang}`] || f.text_en) && <p>{f[`text_${lang}`] || f.text_en}</p>}
                </div>
              </li>
            ))}
          </ul>
        )}
        {L('body') && <p className="wn-body">{L('body')}</p>}
        <div className={`wn-cta-wrap ${st.cta_place === 'sticky' ? 'is-sticky' : ''}`}>
          <button type="button" className={`btn primary wn-cta ${st.cta_width === 'auto' ? 'is-auto' : ''}`} onClick={() => close(ann.cta_action || 'close')}>
            <span>{L('cta_label') || t.close}</span>
          </button>
        </div>
        {ann.allow_dismiss && (
          <label className="wn-never">
            <input type="checkbox" checked={never} onChange={(e) => setNever(e.target.checked)} />
            <span>{t.wnNever}</span>
          </label>
        )}
        {L('footnote') && <p className="wn-foot">{L('footnote')}</p>}
      </section>
    </div>
  );
}
