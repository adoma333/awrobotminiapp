import React from 'react';
import boy from '../assets/icons/boy.webp';
import girl from '../assets/icons/girl.webp';

// صورة شخصية (فتى / فتاة) داخل إطار دائري بلون الشعار
export default function Avatar({ kind = 'boy', size = 64, src }) {
  return (
    <span className="avatar" style={{ width: size, height: size }} aria-hidden="true">
      <img src={src || (kind === 'girl' ? girl : boy)} alt="" width={size} height={size} />
    </span>
  );
}
