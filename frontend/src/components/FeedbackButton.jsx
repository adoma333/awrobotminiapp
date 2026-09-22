import React, { useState } from 'react';
import { sendFeedback } from '../api';
import { haptic } from '../telegram';
import { useToast } from './Toast';

// زر عائم لجمع تقييم ونص ملاحظة قصير من المستخدم وإرساله لقناة الأدمن.
export default function FeedbackButton({ t }) {
  const [open, setOpen] = useState(false);
  const [rating, setRating] = useState(0);
  const [message, setMessage] = useState('');
  const [sending, setSending] = useState(false);
  const notify = useToast();

  function close() {
    setOpen(false);
    setRating(0);
    setMessage('');
  }

  async function submit() {
    if (!rating || sending) return;
    setSending(true);
    try {
      await sendFeedback(rating, message);
      haptic.success();
      notify(t.feedbackSent, 'success');
      close();
    } catch {
      haptic.error();
      notify(t.feedbackErr, 'error');
    } finally {
      setSending(false);
    }
  }

  return (
    <>
      <button type="button" className="fab-feedback" onClick={() => setOpen(true)}>
        <span>⭐</span> {t.feedbackBtn}
      </button>

      {open && (
        <div className="modal-backdrop" role="dialog" aria-modal="true" onClick={close}>
          <div className="modal-sheet" onClick={(e) => e.stopPropagation()}>
            <h2>{t.feedbackTitle}</h2>
            <p className="sub">{t.feedbackSub}</p>
            <div className="star-row" dir="ltr">
              {[1, 2, 3, 4, 5].map((n) => (
                <button
                  key={n}
                  type="button"
                  className={`star ${n <= rating ? 'on' : ''}`}
                  aria-label={`${n}`}
                  onClick={() => {
                    haptic.select();
                    setRating(n);
                  }}
                >
                  ★
                </button>
              ))}
            </div>
            <textarea
              className="feedback-text"
              rows={3}
              placeholder={t.feedbackPh}
              value={message}
              maxLength={1000}
              onChange={(e) => setMessage(e.target.value)}
            />
            <div className="ob-actions">
              <button type="button" className="btn ghost" onClick={close}>
                <span>{t.close}</span>
              </button>
              <button type="button" className="btn primary" disabled={!rating || sending} onClick={submit}>
                <span>{sending ? t.sending : t.feedbackSend}</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
