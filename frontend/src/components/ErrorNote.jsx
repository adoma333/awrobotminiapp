import React, { useState } from 'react';
import Icon from './Icon';
import { reportError } from '../api';
import { contactSupportAbout, currentPage } from '../support';

/** رسالة خطأ موحّدة داخل الصفحات + زر "تواصل مع الدعم" بجانبها مباشرة. */
export default function ErrorNote({ t, children, kind = 'operation', code = '', message = '', errRef = '', className = '' }) {
  const [copied, setCopied] = useState(false);
  async function contact() {
    const r = await contactSupportAbout(t, { kind, code, message: message || String(children || ''), ref: errRef, page: currentPage() }, reportError);
    setCopied(r.copied && !r.opened);
  }
  return (
    <div className={`banner-error err-note ${className}`} role="alert">
      <Icon name="alert" size={18} className="err-ic" />
      <span className="err-text">{children}{copied && <small className="err-copied">{t.errCopied}</small>}</span>
      <button type="button" className="err-support" onClick={contact}>
        <Icon name="headset" size={16} />
        <span>{t.contactSupport}</span>
      </button>
    </div>
  );
}
