import React, { useEffect, useState } from 'react';
import Icon from './Icon';
import useOnlineStatus from '../hooks/useOnlineStatus';
import { onAppError, emitAppError } from '../errors';
import { reportError } from '../api';
import { contactSupportAbout, currentPage } from '../support';
import { haptic } from '../telegram';

/**
 * معالج الأخطاء العام: شبكة (انقطاع/مهلة)، خادم (5xx)، عمليات، واستثناءات الواجهة غير المتوقعة.
 * رسالة واضحة + زر "تواصل مع الدعم" يفتح محادثة الدعم مع تفاصيل الخطأ معبّأة تلقائيًا.
 */
export default function ErrorCenter({ t }) {
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState('');
  const online = useOnlineStatus();

  useEffect(() => onAppError((e) => {
    haptic.error();
    setNote('');
    setErr(e);
  }), []);

  useEffect(() => {
    const onErr = (ev) => {
      if (!ev?.message || /ResizeObserver|Script error/i.test(ev.message)) return;
      emitAppError({ kind: 'ui', code: 'js_error', message: `${ev.message}`.slice(0, 300), page: currentPage() });
    };
    const onRej = (ev) => {
      const r = ev?.reason;
      if (!r || r.status !== undefined) return; // أخطاء الطلبات تُعالَج في api.js
      emitAppError({ kind: 'ui', code: 'unhandled_rejection', message: String(r?.message || r).slice(0, 300), page: currentPage() });
    };
    window.addEventListener('error', onErr);
    window.addEventListener('unhandledrejection', onRej);
    return () => {
      window.removeEventListener('error', onErr);
      window.removeEventListener('unhandledrejection', onRej);
    };
  }, []);

  // عاد الاتصال: رسالة الشبكة لم تعد صحيحة
  useEffect(() => {
    if (online && err?.kind === 'network') setErr(null);
  }, [online]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!err) return null;
  const offline = err.kind === 'network';
  const title = offline ? (online ? t.errNetTitle : t.errOfflineTitle) : err.kind === 'server' ? t.errServerTitle : err.kind === 'operation' ? t.errOpTitle : t.errUiTitle;
  const body = offline ? t.errNetBody : err.kind === 'server' ? t.errServerBody : err.kind === 'operation' ? (err.text || t.errOpBody) : t.errUiBody;

  async function contact() {
    setBusy(true);
    try {
      const r = await contactSupportAbout(t, err, reportError);
      setNote(r.opened ? t.errOpened : t.errCopied);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={`err-center is-${err.kind}`} role="alert" aria-live="assertive">
      <span className="err-center-ic"><Icon name={offline ? 'wifiOff' : 'alert'} size={20} /></span>
      <div className="err-center-text">
        <b>{title}</b>
        <span>{body}</span>
        {err.ref && <small dir="ltr">{err.ref}</small>}
        {note && <small className="err-copied">{note}</small>}
      </div>
      <div className="err-center-actions">
        <button type="button" className="err-support" onClick={contact} disabled={busy}>
          <Icon name="headset" size={16} />
          <span>{t.contactSupport}</span>
        </button>
        <button type="button" className="err-close" aria-label={t.close} onClick={() => setErr(null)}>
          <Icon name="close" size={16} />
        </button>
      </div>
    </div>
  );
}

/** حاجز أخطاء الواجهة: أي انهيار في مكوّن يُظهر شاشة لطيفة بدل صفحة بيضاء. */
export class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { failed: false, ref: '' };
  }

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error) {
    const e = { kind: 'ui', code: 'render_crash', message: String(error?.message || error).slice(0, 300), page: currentPage() };
    reportError(e).then((r) => this.setState({ ref: r?.ref || '' })).catch(() => {});
  }

  render() {
    const { t } = this.props;
    if (!this.state.failed) return this.props.children;
    return (
      <div className="stage crash-screen" role="alert">
        <span className="crash-ic"><Icon name="alert" size={30} /></span>
        <h1>{t.errUiTitle}</h1>
        <p className="sub">{t.errCrashBody}</p>
        {this.state.ref && <p className="muted" dir="ltr">{this.state.ref}</p>}
        <div className="crash-actions">
          <button type="button" className="btn primary" onClick={() => window.location.reload()}><span>{t.errReload}</span></button>
          <button type="button" className="btn soft" onClick={() => contactSupportAbout(t, { kind: 'ui', code: 'render_crash', ref: this.state.ref, page: currentPage() }, reportError)}>
            <span>{t.contactSupport}</span>
          </button>
        </div>
      </div>
    );
  }
}
