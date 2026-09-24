import React, { useEffect, useState } from 'react';
import light from '../assets/icons/light.webp';
import telegram from '../assets/icons/telegram.svg';
import wallet from '../assets/icons/wallet.webp';

// عرض توضيحي متحرك لمسار العمل: تلجرام ← البوت ← محرك n8n ← قاعدة البيانات/الدفع/جسر MT5 ← سيرفر الوسيط
const NODES = {
  tg: { x: 70, y: 46, label: 'Telegram', img: telegram },
  app: { x: 290, y: 46, label: 'Mini App' },
  bot: { x: 180, y: 128, label: 'AW Bot · FastAPI' },
  db: { x: 62, y: 330, label: 'Firestore' },
  pay: { x: 298, y: 330, label: 'TON · Pay', img: wallet },
  bridge: { x: 118, y: 420, label: 'MT5 Bridge · Wine' },
  broker: { x: 262, y: 420, label: 'Broker Server' },
};
const ENGINE = { x: 180, y: 232 };

const EDGES = [
  { id: 'tg-bot', d: 'M70 64 C70 100 150 100 172 112' },
  { id: 'app-bot', d: 'M290 64 C290 100 210 100 188 112' },
  { id: 'bot-eng', d: 'M180 146 L180 188' },
  { id: 'eng-db', d: 'M146 256 C100 280 70 290 64 312' },
  { id: 'eng-pay', d: 'M214 256 C260 280 294 290 296 312' },
  { id: 'eng-bridge', d: 'M168 276 C150 330 124 360 120 402' },
  { id: 'bridge-broker', d: 'M160 420 L220 420' },
  { id: 'pay-bot', d: 'M306 312 C340 230 300 160 214 132' },
];

// تشغيلات نموذجية تُضاء مساراتها بالتتابع
const RUNS = [
  { name: 'runLink', edges: ['app-bot', 'bot-eng', 'eng-bridge', 'bridge-broker', 'eng-db'], ms: 1840 },
  { name: 'runSync', edges: ['bot-eng', 'eng-bridge', 'bridge-broker', 'eng-db'], ms: 920 },
  { name: 'runPay', edges: ['app-bot', 'bot-eng', 'eng-pay', 'pay-bot', 'eng-db'], ms: 640 },
  { name: 'runNotify', edges: ['eng-db', 'bot-eng', 'tg-bot'], ms: 210 },
  { name: 'runDigest', edges: ['bot-eng', 'eng-db', 'tg-bot'], ms: 480 },
];

function Node({ n }) {
  const w = 104;
  return (
    <g className="flow-node" transform={`translate(${n.x - w / 2} ${n.y - 18})`}>
      <rect width={w} height="36" rx="10" />
      {n.img && <image href={n.img} x="8" y="8" width="20" height="20" />}
      <text x={n.img ? 34 : w / 2} y="22" textAnchor={n.img ? 'start' : 'middle'}>{n.label}</text>
    </g>
  );
}

export default function N8nFlow({ t }) {
  const [i, setI] = useState(0);
  const [log, setLog] = useState([]);
  const run = RUNS[i % RUNS.length];

  useEffect(() => {
    const id = setInterval(() => setI((n) => n + 1), 2600);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const at = new Date().toLocaleTimeString('en-GB', { hour12: false });
    const ms = Math.round(run.ms * (0.8 + Math.random() * 0.4));
    setLog((l) => (l[0]?.id === i ? l : [{ id: i, at, name: run.name, ms }, ...l].slice(0, 5)));
  }, [i]);

  return (
    <div className="section n8n">
      <div className="section-head">
        <h2>{t.anN8n}</h2>
        <span className="tag">{t.anDemo}</span>
      </div>
      <p className="sub">{t.anN8nSub}</p>

      <svg className="flow" viewBox="0 0 360 450" role="img" aria-label={t.anN8n} dir="ltr">
        <defs>
          <radialGradient id="eng-glow">
            <stop offset="0" stopColor="#ff8a00" stopOpacity="0.55" />
            <stop offset="1" stopColor="#ff8a00" stopOpacity="0" />
          </radialGradient>
          <pattern id="flow-grid" width="18" height="18" patternUnits="userSpaceOnUse">
            <circle cx="1" cy="1" r="1" fill="rgba(255,255,255,0.06)" />
          </pattern>
        </defs>
        <rect width="360" height="450" fill="url(#flow-grid)" />

        {EDGES.map((e) => (
          <g key={e.id} className={`flow-edge ${run.edges.includes(e.id) ? 'is-live' : ''}`}>
            <path id={`fe-${e.id}`} d={e.d} className="edge-base" />
            <path d={e.d} className="edge-flow" />
            {run.edges.includes(e.id) && (
              <circle r="3.5" className="edge-pulse">
                <animateMotion dur="1.3s" repeatCount="indefinite" begin={`${run.edges.indexOf(e.id) * 0.18}s`}>
                  <mpath href={`#fe-${e.id}`} />
                </animateMotion>
              </circle>
            )}
          </g>
        ))}

        <g className="engine" transform={`translate(${ENGINE.x} ${ENGINE.y})`}>
          <circle r="78" fill="url(#eng-glow)" className="engine-glow" />
          <circle r="46" className="engine-ring" />
          <image href={light} x="-44" y="-44" width="88" height="88" className="engine-orb" />
          <text y="64" textAnchor="middle" className="engine-label">n8n Engine</text>
        </g>

        {Object.entries(NODES).map(([k, n]) => (
          <Node key={k} n={n} />
        ))}
      </svg>

      <ul className="flow-log" aria-live="polite">
        {log.map((row, idx) => (
          <li key={row.id} className={idx === 0 ? 'is-new' : ''}>
            <span className="dot up" />
            <span className="flow-log-name">{t[row.name]}</span>
            <bdi className="muted" dir="ltr">{row.ms}ms · {row.at}</bdi>
          </li>
        ))}
      </ul>
    </div>
  );
}
