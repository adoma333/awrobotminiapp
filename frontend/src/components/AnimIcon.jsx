import React, { useState } from 'react';

// أي ملف assets/anim/<name>.webm يحلّ تلقائيًا محل الأيقونة الثابتة بنفس الاسم
const FILES = import.meta.glob('../assets/anim/*.webm', { eager: true, import: 'default' });
const ANIM = Object.fromEntries(Object.entries(FILES).map(([p, url]) => [p.split('/').pop().replace('.webm', ''), url]));
const CAN_WEBM = typeof document !== 'undefined' && Boolean(document.createElement('video').canPlayType?.('video/webm; codecs="vp9"'));

/** أيقونة المستويات والجوائز: WebM متحركة إن وُجدت ودعمها الجهاز، وإلا الصورة الحالية (نفس المقاس والمكان). */
export default function AnimIcon({ name, src, className, alt = '' }) {
  const [failed, setFailed] = useState(false);
  const video = CAN_WEBM && !failed ? ANIM[name] : null;
  if (!video) return <img className={className} src={src} alt={alt} />;
  return (
    <video className={className} src={video} poster={src} autoPlay loop muted playsInline aria-hidden="true" onError={() => setFailed(true)} />
  );
}
