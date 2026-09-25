import React, { useEffect, useState } from 'react';
import ErrorNote from './ErrorNote';
import QRCode from 'qrcode';
import { paymentStatus } from '../api';
import { copyText, haptic } from '../telegram';
import { useToast } from './Toast';
import Icon from './Icon';

const STEPS = ['waiting', 'confirming', 'finished'];
const STATUS_STEP = { waiting: 0, partially_paid: 0, confirming: 1, confirmed: 1, sending: 1, finished: 2 };

/** بوابة الدفع المخصّصة: عنوان + مبلغ + QR + عدّاد + حالة حية، بتصميم البوت نفسه (تعمل فوق NOWPayments). */
export default function CryptoPay({ t, pay, onFinished, onCancel }) {
  const notify = useToast();
  const [qr, setQr] = useState('');
  const [status, setStatus] = useState('waiting');
  const [now, setNow] = useState(Date.now());
  const exp = pay.expires_at ? Date.parse(pay.expires_at) : null;
  const left = exp ? Math.max(0, exp - now) : null;
  const step = STATUS_STEP[status] ?? 0;
  const failed = ['failed', 'expired', 'refunded'].includes(status);

  useEffect(() => {
    QRCode.toDataURL(pay.pay_address, { width: 360, margin: 1, color: { dark: '#000000', light: '#ffffff' } })
      .then(setQr)
      .catch(() => setQr(''));
  }, [pay.pay_address]);

  useEffect(() => {
    const tick = setInterval(() => setNow(Date.now()), 1000);
    const poll = setInterval(() => {
      paymentStatus(pay.order_id)
        .then((r) => {
          if (!r.status) return;
          setStatus(r.status);
          if (r.status === 'finished') onFinished();
        })
        .catch(() => {});
    }, 8000);
    return () => {
      clearInterval(tick);
      clearInterval(poll);
    };
  }, [pay.order_id]);

  async function copy(v) {
    if (await copyText(String(v))) {
      haptic.success();
      notify(t.copied, 'success');
    }
  }

  const mm = left == null ? null : `${String(Math.floor(left / 60000)).padStart(2, '0')}:${String(Math.floor((left % 60000) / 1000)).padStart(2, '0')}`;
  const symbol = String(pay.pay_currency || '').toUpperCase().replace(/(TRC20|BSC|ERC20)$/, '');

  return (
    <section className="step crypto-pay">
      <h1>{t.cpTitle}</h1>
      <p className="sub">{t.cpSub}</p>

      <div className="cp-steps">
        {STEPS.map((s, i) => (
          <div key={s} className={`cp-step ${i < step ? 'done' : ''} ${i === step && !failed ? 'on' : ''}`}>
            <span className="cp-dot" />
            <small>{t[`cp_${s}`]}</small>
          </div>
        ))}
      </div>

      <div className="cp-card">
        {qr ? <img className="cp-qr" src={qr} alt="QR" /> : <div className="cp-qr loader" />}
        <div className="cp-field">
          <span className="muted">{t.cpAmount}</span>
          <div className="cp-value">
            <strong dir="ltr">{pay.pay_amount} {symbol}</strong>
            <button type="button" className="icon-btn small" onClick={() => copy(pay.pay_amount)} aria-label={t.copy}><Icon name="copy" size={16} /></button>
          </div>
        </div>
        <div className="cp-field">
          <span className="muted">{t.cpNetwork}</span>
          <div className="cp-value"><b dir="ltr">{pay.network}</b></div>
        </div>
        <div className="cp-field">
          <span className="muted">{t.cpAddress}</span>
          <div className="cp-value">
            <code dir="ltr">{pay.pay_address}</code>
            <button type="button" className="icon-btn small" onClick={() => copy(pay.pay_address)} aria-label={t.copy}><Icon name="copy" size={16} /></button>
          </div>
        </div>
        {pay.payin_extra_id && (
          <div className="cp-field cp-memo">
            <span>{t.cpMemo}</span>
            <div className="cp-value">
              <code dir="ltr">{pay.payin_extra_id}</code>
              <button type="button" className="icon-btn small" onClick={() => copy(pay.payin_extra_id)} aria-label={t.copy}><Icon name="copy" size={16} /></button>
            </div>
          </div>
        )}
        {mm && !failed && <div className="cp-timer">{t.cpExpires} <b dir="ltr">{mm}</b></div>}
      </div>

      {failed ? <ErrorNote t={t} kind="operation" code="crypto_payment_failed">{t.cpFailed}</ErrorNote> : <p className="muted small-note">{t.cpNote}</p>}

      <div className="actions">
        <button type="button" className="btn ghost" onClick={onCancel}>
          <span>{t.payCancel}</span>
        </button>
      </div>
    </section>
  );
}
