import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import Icon from './Icon';
import { getSupportThread, sendSupport, supportAction, supportMediaUrl } from '../api';
import { haptic, openExternal, openTelegramLink, tg } from '../telegram';
import { fill } from '../i18n';

// ─────────── أصوات مركز الدعم (WebAudio — بلا ملفات) ───────────
const MUTE_KEY = 'aw_support_mute';
let actx = null;
function audio() {
  try {
    actx = actx || new (window.AudioContext || window.webkitAudioContext)();
    if (actx.state === 'suspended') actx.resume();
    return actx;
  } catch {
    return null;
  }
}
function tone(freqs, dur, gain = 0.07, type = 'sine') {
  const a = audio();
  if (!a) return;
  const now = a.currentTime;
  freqs.forEach((f, i) => {
    const o = a.createOscillator();
    const g = a.createGain();
    o.type = type;
    o.frequency.setValueAtTime(f, now + i * dur * 0.55);
    g.gain.setValueAtTime(0, now + i * dur * 0.55);
    g.gain.linearRampToValueAtTime(gain, now + i * dur * 0.55 + 0.015);
    g.gain.exponentialRampToValueAtTime(0.0001, now + i * dur * 0.55 + dur);
    o.connect(g).connect(a.destination);
    o.start(now + i * dur * 0.55);
    o.stop(now + i * dur * 0.55 + dur + 0.02);
  });
}
const SOUND = {
  incoming: () => tone([880, 1318.5], 0.28, 0.06),
  sent: () => tone([540], 0.09, 0.05, 'triangle'),
  agent: () => tone([659.3, 880, 1174.7], 0.26, 0.06),
};

// صورة مرفقة: تصغير على الجهاز (≤1600px، JPEG) قبل الرفع — أسرع وأخف
function compressImage(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      const k = Math.min(1, 1600 / Math.max(img.width, img.height));
      const c = document.createElement('canvas');
      c.width = Math.round(img.width * k);
      c.height = Math.round(img.height * k);
      c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
      URL.revokeObjectURL(url);
      resolve(c.toDataURL('image/jpeg', 0.82));
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error('bad_image'));
    };
    img.src = url;
  });
}

const STATUS_TONE = { open: 'is-open', in_progress: 'is-progress', escalated: 'is-escalated', resolved: 'is-resolved', closed: 'is-closed' };
const isTouch = () => window.matchMedia?.('(pointer: coarse)').matches;

function timeOf(at, lang) {
  if (!at) return '';
  return new Date(at * 1000).toLocaleTimeString(lang === 'ar' ? 'ar' : 'en', { hour: '2-digit', minute: '2-digit' });
}

/**
 * مركز الدعم داخل التطبيق (صفحة كاملة): محادثة فورية مع المساعد الذكي وفريق الدعم، مرفقات صور، أصوات للردود،
 * مؤشر «يكتب…»، ردود سريعة، تقييم، طلب موظف، وتأكيد الإجراءات الحساسة — مرتبط بمركز الأخطاء برقم الخطأ.
 */
export default function SupportCenter({ t, lang, open, errorRef, draft, onClose, onLinkAccount }) {
  const [thread, setThread] = useState({ ticket: null, messages: [], config: null });
  const [text, setText] = useState('');
  const [image, setImage] = useState('');
  const [sending, setSending] = useState(false);
  const [waiting, setWaiting] = useState(false); // أرسلنا وننتظر الرد
  const [err, setErr] = useState('');
  const [muted, setMuted] = useState(() => {
    try {
      return localStorage.getItem(MUTE_KEY) === '1';
    } catch {
      return false;
    }
  });
  const [zoom, setZoom] = useState('');
  const [loaded, setLoaded] = useState(false);
  const seen = useRef(null);
  const bodyRef = useRef(null);
  const inputRef = useRef(null);
  const fileRef = useRef(null);
  const sentRefs = useRef(new Set());
  const cfg = thread.config || {};
  const sounds = cfg.sounds !== false && !muted;

  const load = useCallback(async () => {
    try {
      const r = await getSupportThread(lang);
      const d = { ticket: r?.ticket || null, messages: Array.isArray(r?.messages) ? r.messages : [], config: r?.config || null };
      setThread(d);
      setLoaded(true);
      const ids = new Set(d.messages.map((m) => m.id));
      if (seen.current) {
        const fresh = d.messages.filter((m) => !seen.current.has(m.id) && m.role !== 'user');
        if (fresh.length) {
          setWaiting(false);
          haptic.success();
          if (sounds) (fresh.some((m) => m.role === 'agent') ? SOUND.agent : SOUND.incoming)();
        }
      }
      seen.current = ids;
      return d;
    } catch {
      setLoaded(true);
      return null;
    }
  }, [lang, sounds]);

  // فتح/إغلاق: تحميل فوري + زر الرجوع في تلجرام + قفل تمرير الصفحة خلفه
  useEffect(() => {
    if (!open) return undefined;
    seen.current = null;
    audio();
    load();
    if (draft) setText(draft);
    const back = () => onClose();
    tg?.BackButton?.show?.();
    tg?.BackButton?.onClick?.(back);
    document.body.classList.add('sc-lock');
    return () => {
      tg?.BackButton?.offClick?.(back);
      tg?.BackButton?.hide?.();
      document.body.classList.remove('sc-lock');
    };
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  // فتح من رسالة خطأ: التذكرة تُنشأ فورًا مربوطة بالخطأ ويبدأ المساعد التحليل
  useEffect(() => {
    if (!open || !errorRef || sentRefs.current.has(errorRef)) return;
    sentRefs.current.add(errorRef);
    setWaiting(true);
    sendSupport({ errorRef, lang }).then(load).catch(() => setWaiting(false));
  }, [open, errorRef]); // eslint-disable-line react-hooks/exhaustive-deps

  // تحديث دوري: أسرع أثناء انتظار الرد أو كتابة المساعد، ويتوقف والتطبيق في الخلفية
  const typing = Boolean(thread.ticket?.typing);
  useEffect(() => {
    if (!open) return undefined;
    const ms = waiting || typing ? 1500 : 5000;
    const id = setInterval(() => {
      if (document.visibilityState === 'visible') load();
    }, ms);
    return () => clearInterval(id);
  }, [open, waiting, typing, load]);

  // مهلة الانتظار: لا يبقى مؤشر الكتابة للأبد إن تأخر الرد
  useEffect(() => {
    if (!waiting) return undefined;
    const id = setTimeout(() => setWaiting(false), 45000);
    return () => clearTimeout(id);
  }, [waiting]);

  const count = thread.messages.length;
  useLayoutEffect(() => {
    const el = bodyRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [count, waiting, typing, open]);

  async function send(value) {
    const body = (value ?? text).trim();
    if ((!body && !image) || sending) return;
    setSending(true);
    setErr('');
    try {
      await sendSupport({ text: body, image, lang });
      if (sounds) SOUND.sent();
      haptic.select();
      setText('');
      setImage('');
      setWaiting(true);
      await load();
    } catch (e) {
      haptic.error();
      setErr(e?.detail === 'attachments_disabled' ? t.scNoAttach : e?.detail === 'bad_image' ? t.scBadImage : e?.status === 503 ? t.scDisabled : t.scSendFail);
    } finally {
      setSending(false);
      inputRef.current?.focus();
    }
  }

  async function act(b) {
    haptic.select();
    if (b.kind === 'url') {
      if (/[?&]view=link/.test(b.url)) {
        onLinkAccount?.();
        onClose();
      } else if (/^https:\/\/t\.me\//.test(b.url)) openTelegramLink(b.url);
      else openExternal(b.url);
      return;
    }
    try {
      await supportAction(b.kind, b.tid, b.arg);
      if (b.kind !== 'csat') setWaiting(true);
      await load();
    } catch {
      setErr(t.scSendFail);
    }
  }

  async function pickFile(e) {
    const f = e.target.files?.[0];
    e.target.value = '';
    if (!f) return;
    try {
      const data = await compressImage(f);
      if (data.length > 4_000_000) throw new Error('big');
      setImage(data);
      setErr('');
    } catch {
      setErr(t.scBadImage);
    }
  }

  function toggleMute() {
    const v = !muted;
    setMuted(v);
    try {
      localStorage.setItem(MUTE_KEY, v ? '1' : '0');
    } catch {
      /* تخزين غير متاح */
    }
    if (!v) SOUND.incoming();
  }

  if (!open) return null;
  const tk = thread.ticket;
  const msgs = thread.messages;
  const lastBtnIdx = msgs.reduce((acc, m, i) => (m.buttons?.length ? i : acc), -1);
  const userCount = msgs.filter((m) => m.role === 'user').length;
  const active = !tk || ['open', 'in_progress', 'escalated'].includes(tk.status);

  return (
    <div className="sc" role="dialog" aria-modal="true" aria-label={t.scTitle} dir={t.dir}>
      <header className="sc-head">
        <button type="button" className="sc-icon-btn" aria-label={t.close} onClick={onClose}>
          <Icon name="close" size={20} />
        </button>
        <div className="sc-agent">
          <span className={`sc-avatar ${cfg.ai_online ? 'is-online' : ''}`}><Icon name="headset" size={20} /></span>
          <div className="sc-agent-text">
            <b>{t.scTitle}</b>
            <small>{tk ? fill(t.scTicket, { id: tk.id }) : cfg.ai_online ? t.scOnline : t.scTeam}</small>
          </div>
        </div>
        <button type="button" className="sc-icon-btn" aria-label={muted ? t.scUnmute : t.scMute} aria-pressed={!muted} onClick={toggleMute}>
          <Icon name={muted ? 'soundOff' : 'sound'} size={20} />
        </button>
      </header>

      {tk && (
        <div className="sc-status" role="status">
          <span className={`sc-pill ${STATUS_TONE[tk.status] || ''}`}>{t[`scSt_${tk.status}`] || tk.status}</span>
          {tk.priority && <span className={`sc-pill is-${tk.priority}`}>{t[`scPr_${tk.priority}`] || tk.priority}</span>}
          {tk.csat?.score && <span className="sc-pill">{'★'.repeat(tk.csat.score)}</span>}
        </div>
      )}

      <div className="sc-body" ref={bodyRef} aria-live="polite">
        {!loaded ? (
          <div className="sc-skel"><span /><span /><span /></div>
        ) : (
          <>
            <div className="sc-msg is-ai is-welcome">
              <span className="sc-who">{t.scAssistant}</span>
              <p dir="auto">{cfg.welcome || t.scWelcome}</p>
            </div>
            {msgs.map((m, i) => (
              <div key={m.id || i} className={`sc-msg is-${m.role}`}>
                {m.role === 'ai' && <span className="sc-who">{t.scAssistant}</span>}
                {m.role === 'agent' && <span className="sc-who is-agent">{t.scAgent}</span>}
                {m.image && (
                  <button type="button" className="sc-img" onClick={() => setZoom(supportMediaUrl(m.image))} aria-label={t.scViewImage}>
                    <img src={supportMediaUrl(m.image)} alt="" loading="lazy" />
                  </button>
                )}
                {m.text && m.text !== "[صورة]" && <p dir="auto">{m.text}</p>}
                {m.buttons?.length > 0 && i === lastBtnIdx && (
                  <div className="sc-actions">
                    {m.buttons.some((b) => b.kind === 'csat') && !tk?.csat ? (
                      <div className="sc-stars" role="group" aria-label={t.scRate}>
                        {[1, 2, 3, 4, 5].map((n) => (
                          <button key={n} type="button" onClick={() => act({ kind: 'csat', tid: m.buttons[0].tid, arg: String(n) })} aria-label={`${n}`}>★</button>
                        ))}
                      </div>
                    ) : null}
                    {m.buttons.filter((b) => b.kind !== 'csat').map((b, j) => (b.kind === 'human' && !['open', 'in_progress'].includes(tk?.status) ? null : (
                      <button key={j} type="button" className={`sc-btn ${b.kind === 'act' && b.arg === 'yes' ? 'is-primary' : ''}`} onClick={() => act(b)}>
                        {b.label}
                      </button>
                    )))}
                  </div>
                )}
                {m.role !== 'notice' && <time dir="ltr">{timeOf(m.at, lang)}</time>}
              </div>
            ))}
            {(waiting || typing) && (
              <div className="sc-msg is-ai sc-typing" aria-label={t.scTyping}>
                <span /><span /><span />
              </div>
            )}
          </>
        )}
      </div>

      {loaded && userCount === 0 && !waiting && (cfg.quick || []).length > 0 && (
        <div className="sc-quick">
          {cfg.quick.map((q) => (
            <button key={q} type="button" onClick={() => send(q)} disabled={sending}>{q}</button>
          ))}
        </div>
      )}

      {err && <p className="sc-err" role="alert">{err}</p>}
      {image && (
        <div className="sc-attach">
          <img src={image} alt="" />
          <span>{t.scImageReady}</span>
          <button type="button" className="sc-icon-btn" aria-label={t.close} onClick={() => setImage('')}><Icon name="close" size={16} /></button>
        </div>
      )}

      <form
        className="sc-compose"
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
      >
        {cfg.attachments !== false && (
          <>
            <button type="button" className="sc-icon-btn" aria-label={t.scAttach} onClick={() => fileRef.current?.click()} disabled={sending}>
              <Icon name="image" size={20} />
            </button>
            <input ref={fileRef} type="file" accept="image/*" hidden onChange={pickFile} />
          </>
        )}
        <textarea
          ref={inputRef}
          rows={1}
          value={text}
          maxLength={2000}
          placeholder={active ? t.scPlaceholder : t.scPlaceholderNew}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && !isTouch()) {
              e.preventDefault();
              send();
            }
          }}
        />
        <button type="submit" className="sc-send" aria-label={t.scSend} disabled={sending || (!text.trim() && !image)}>
          <Icon name="send" size={20} />
        </button>
      </form>

      {zoom && (
        <button type="button" className="sc-zoom" onClick={() => setZoom('')} aria-label={t.close}>
          <img src={zoom} alt="" />
        </button>
      )}
    </div>
  );
}
