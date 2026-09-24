import React, { useEffect, useRef, useState } from 'react';
import { claimScratch, openSealedPrize, revealScratch } from '../api';
import { haptic } from '../telegram';
import { prizeIcon, prizeLabel } from '../rewards';
import congrats from '../assets/icons/congrats.gif';

const REVEAL_AT = 0.5; // نسبة المساحة المكشوفة التي تُطلق الاستلام
const BRUSH = 38;

// مؤثر صوتي قصير (WebAudio، بلا ملفات): نغمات صاعدة
function playChime() {
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    [660, 880, 1320].forEach((freq, i) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      const t0 = ctx.currentTime + i * 0.09;
      osc.type = 'triangle';
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.0001, t0);
      gain.gain.exponentialRampToValueAtTime(0.25, t0 + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.35);
      osc.connect(gain).connect(ctx.destination);
      osc.start(t0);
      osc.stop(t0 + 0.4);
    });
    setTimeout(() => ctx.close(), 1000);
  } catch {
    /* الصوت اختياري */
  }
}

function celebrate() {
  haptic.success();
  playChime();
  import('canvas-confetti')
    .then(({ default: confetti }) => {
      const colors = ['#FF8A00', '#FF5A00', '#FFD27A', '#F5EFE8'];
      confetti({ particleCount: 140, spread: 80, origin: { y: 0.55 }, colors, zIndex: 200 });
      setTimeout(() => confetti({ particleCount: 80, spread: 120, origin: { y: 0.45 }, colors, zIndex: 200 }), 250);
    })
    .catch(() => {});
}

// الطبقة العلوية: سبيكة ذهبية/رمادية مع لمعات
function paintCover(canvas, hint) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  const g = ctx.createLinearGradient(0, 0, w, h);
  g.addColorStop(0, '#b8892f');
  g.addColorStop(0.35, '#f3d27a');
  g.addColorStop(0.55, '#a7a39c');
  g.addColorStop(0.8, '#e6c265');
  g.addColorStop(1, '#8a6a24');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, w, h);
  ctx.globalAlpha = 0.18;
  for (let i = 0; i < 90; i += 1) {
    ctx.fillStyle = i % 2 ? '#fff' : '#6b5520';
    ctx.fillRect((i * 97) % w, (i * 53) % h, 2, 2);
  }
  ctx.globalAlpha = 1;
  ctx.fillStyle = 'rgba(40, 28, 6, 0.75)';
  ctx.font = '700 17px system-ui, sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(`✦ ${hint} ✦`, w / 2, h / 2);
}

function clearedRatio(canvas) {
  const { width, height } = canvas;
  const data = canvas.getContext('2d').getImageData(0, 0, width, height).data;
  let clear = 0;
  let total = 0;
  for (let i = 3; i < data.length; i += 4 * 16) {
    total += 1;
    if (data[i] < 128) clear += 1;
  }
  return total ? clear / total : 0;
}

/**
 * بطاقة خدش: الجائزة تُولَّد على الخادم (claim) وتُعرض تحت الطبقة؛ الواجهة لا تحدد أي جائزة.
 * عند كشف أكثر من 50% تُستدعى reveal تلقائيًا مع مؤثرات الاحتفال.
 */
export default function ScratchCard({ t, cardId, onRevealed, onNeedPhone }) {
  const canvasRef = useRef(null);
  const drawing = useRef(false);
  const last = useRef(null);
  const moves = useRef(0);
  const doneRef = useRef(false); // يمنع استدعاء reveal مرتين أثناء حركة واحدة
  const [prize, setPrize] = useState(null);
  const [error, setError] = useState('');
  const [done, setDone] = useState(false);

  useEffect(() => {
    claimScratch(cardId)
      .then((r) => setPrize(openSealedPrize(r.token)))
      .catch((e) => {
        if (e.detail === 'phone_verification_required') onNeedPhone?.();
        else setError(e.detail || 'error');
      });
  }, [cardId]);

  useEffect(() => {
    if (prize && canvasRef.current) paintCover(canvasRef.current, t.rwScratchHint);
  }, [prize]);

  const point = (e) => {
    const r = canvasRef.current.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  };

  const scratch = (from, to) => {
    const ctx = canvasRef.current.getContext('2d');
    ctx.globalCompositeOperation = 'destination-out';
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.lineWidth = BRUSH;
    ctx.beginPath();
    ctx.moveTo(from.x, from.y);
    ctx.lineTo(to.x, to.y);
    ctx.stroke();
  };

  const finish = () => {
    if (doneRef.current) return;
    doneRef.current = true;
    setDone(true);
    celebrate();
    revealScratch(cardId)
      .then((reward) => onRevealed?.(reward))
      .catch(() => onRevealed?.(null));
  };

  const onDown = (e) => {
    if (doneRef.current || !prize) return;
    drawing.current = true;
    canvasRef.current.setPointerCapture?.(e.pointerId);
    last.current = point(e);
    scratch(last.current, { x: last.current.x + 0.1, y: last.current.y });
    haptic.select();
  };

  const onMove = (e) => {
    if (!drawing.current || doneRef.current) return;
    const p = point(e);
    scratch(last.current, p);
    last.current = p;
    moves.current += 1;
    if (moves.current % 6 === 0 && clearedRatio(canvasRef.current) >= REVEAL_AT) finish();
  };

  const onUp = () => {
    drawing.current = false;
    if (!doneRef.current && prize && clearedRatio(canvasRef.current) >= REVEAL_AT) finish();
  };

  if (error) return <p className="note warn">{t.rwErr}</p>;

  return (
    <div className={`scratch ${done ? 'is-done' : ''}`}>
      <div className="scratch-prize" aria-live="polite">
        {prize ? (
          <>
            <img className="scratch-icon" src={prizeIcon(prize.type)} alt="" />
            {done && <img className="scratch-congrats" src={congrats} alt="" />}
            <strong>{prizeLabel(t, prize)}</strong>
            {done && <span className="muted">{t.rwYouWon}</span>}
          </>
        ) : (
          <div className="loader" role="status" aria-label={t.loading} />
        )}
      </div>
      {prize && (
        <canvas
          ref={canvasRef}
          className="scratch-cover"
          onPointerDown={onDown}
          onPointerMove={onMove}
          onPointerUp={onUp}
          onPointerCancel={onUp}
          aria-label={t.rwScratchHint}
        />
      )}
    </div>
  );
}
