import React, { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { sendFeedback } from '../api';
import { haptic } from '../telegram';
import { openSupport } from '../support';
import { fill } from '../i18n';
import Icon from './Icon';
import { useToast } from './Toast';

const FB_KEY = 'aw_feedback';
function lastFeedback() {
  try {
    return JSON.parse(localStorage.getItem(FB_KEY) || 'null');
  } catch {
    return null;
  }
}

/** نافذة التقييم: نجوم تفاعلية + ملاحظة، ثم رد فريق AW (المساعد الذكي) حسب الرسالة. */
function FeedbackSheet({ t, lang, initial = 0, onClose, onDone }) {
  const [rating, setRating] = useState(initial);
  const [message, setMessage] = useState('');
  const [sending, setSending] = useState(false);
  const [reply, setReply] = useState(null); // { reply, suggest_support }
  const [shown, setShown] = useState('');
  const notify = useToast();
  const faces = ['', '😞', '😕', '🙂', '😊', '🤩'];

  // الرد يظهر حرفًا بحرف (كتابة حيّة)
  useEffect(() => {
    if (!reply?.reply) return undefined;
    let i = 0;
    const id = setInterval(() => {
      i += 2;
      setShown(reply.reply.slice(0, i));
      if (i >= reply.reply.length) clearInterval(id);
    }, 18);
    return () => clearInterval(id);
  }, [reply]);

  async function submit() {
    if (!rating || sending) return;
    setSending(true);
    try {
      const r = await sendFeedback(rating, message.trim(), lang);
      haptic.success();
      try {
        localStorage.setItem(FB_KEY, JSON.stringify({ rating, at: Date.now() }));
      } catch {
        /* تخزين غير متاح */
      }
      onDone?.(rating);
      setReply({ reply: r.reply || t.feedbackSent, suggest_support: Boolean(r.suggest_support) });
    } catch (e) {
      haptic.error();
      notify(e?.status === 429 ? t.fbWait : t.feedbackErr, 'error');
    } finally {
      setSending(false);
    }
  }

  // خارج شجرة الصفحة (document.body): لا تقصّها حركة الصفحة ولا يغطيها شريط التنقل السفلي
  return createPortal(
    <div className="modal-backdrop fb-backdrop" role="dialog" aria-modal="true" onClick={onClose}>
      <div className="modal-sheet fb-sheet" onClick={(e) => e.stopPropagation()}>
        {!reply ? (
          <>
            <span className="fb-face" aria-hidden="true">{faces[rating] || '⭐'}</span>
            <h2>{t.feedbackTitle}</h2>
            <p className="sub">{t.feedbackSub}</p>
            <div className="star-row" dir="ltr">
              {[1, 2, 3, 4, 5].map((n) => (
                <button key={n} type="button" className={`star ${n <= rating ? 'on' : ''}`} aria-label={`${n}`}
                  onClick={() => { haptic.select(); setRating(n); }}>★</button>
              ))}
            </div>
            <textarea className="feedback-text" rows={3} placeholder={rating && rating <= 3 ? t.fbPhLow : t.feedbackPh}
              value={message} maxLength={1000} onChange={(e) => setMessage(e.target.value)} />
            <div className="ob-actions">
              <button type="button" className="btn ghost" onClick={onClose}><span>{t.close}</span></button>
              <button type="button" className="btn primary" disabled={!rating || sending} onClick={submit}>
                <span>{sending ? t.sending : t.feedbackSend}</span>
              </button>
            </div>
          </>
        ) : (
          <div className="fb-reply" aria-live="polite">
            <span className="fb-reply-av"><Icon name="headset" size={20} /></span>
            <b>{t.fbReplyTitle}</b>
            <p dir="auto">{shown}<span className="fb-caret" /></p>
            <div className="ob-actions">
              {reply.suggest_support && (
                <button type="button" className="btn soft" onClick={() => { onClose(); openSupport({ draft: message.trim() }); }}>
                  <span>{t.fbOpenSupport}</span>
                </button>
              )}
              <button type="button" className="btn primary" onClick={onClose}><span>{t.fbThanksClose}</span></button>
            </div>
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}

/** بطاقة التقييم أعلى الرئيسية: ظاهرة وتفاعلية؛ بعد التقييم تتحول لشارة صغيرة قابلة للتعديل. */
export function FeedbackCard({ t, lang }) {
  const [open, setOpen] = useState(0); // 0 = مغلقة، وإلا التقييم المبدئي
  const [last, setLast] = useState(lastFeedback);
  const recent = last && Date.now() - last.at < 14 * 86400000;
  if (recent) {
    return (
      <>
        <button type="button" className="fb-pill" onClick={() => setOpen(last.rating || 5)}>
          <span dir="ltr">{'★'.repeat(last.rating)}</span>
          <span>{fill(t.fbRated, { n: last.rating })}</span>
          <small>{t.fbEdit}</small>
        </button>
        {open > 0 && <FeedbackSheet t={t} lang={lang} initial={open} onClose={() => setOpen(0)} onDone={(r) => setLast({ rating: r, at: Date.now() })} />}
      </>
    );
  }
  return (
    <>
      <section className="fb-card" aria-label={t.fbCardTitle}>
        <div className="fb-card-text">
          <b>{t.fbCardTitle}</b>
          <span>{t.fbCardSub}</span>
        </div>
        <div className="fb-card-stars" dir="ltr" role="group" aria-label={t.feedbackTitle}>
          {[1, 2, 3, 4, 5].map((n) => (
            <button key={n} type="button" style={{ animationDelay: `${n * 90}ms` }} aria-label={`${n}`}
              onClick={() => { haptic.select(); setOpen(n); }}>★</button>
          ))}
        </div>
      </section>
      {open > 0 && <FeedbackSheet t={t} lang={lang} initial={open} onClose={() => setOpen(0)} onDone={(r) => setLast({ rating: r, at: Date.now() })} />}
    </>
  );
}

// صف في الإعدادات (يفتح نفس نافذة التقييم)
export default function FeedbackButton({ t, lang }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" className="row row-link" onClick={() => setOpen(true)}>
        <span className="row-label">{t.feedbackBtn}</span>
        <svg className="chev" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M9 6l6 6-6 6" /></svg>
      </button>
      {open && <FeedbackSheet t={t} lang={lang} onClose={() => setOpen(false)} />}
    </>
  );
}
