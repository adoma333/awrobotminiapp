import React, { useEffect, useRef, useState } from 'react';
import light from '../assets/icons/light.webp';
import telegram from '../assets/icons/telegram.svg';
import wallet from '../assets/icons/wallet.webp';

// أيقونات العقد (رسومات SVG داخل المخطط، 20×20)
const GLYPH = {
  app: (
    <g fill="none" stroke="#ff8a00" strokeWidth="1.6" strokeLinecap="round">
      <rect x="5" y="1.5" width="10" height="17" rx="2.2" />
      <path d="M8.5 15.5h3" />
    </g>
  ),
  bot: (
    <g fill="none" stroke="#ff8a00" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="6" width="14" height="10" rx="3" />
      <path d="M10 6V3" />
      <circle cx="10" cy="2.4" r="1" fill="#ff8a00" />
      <circle cx="7.3" cy="11" r="1.3" fill="#ff8a00" stroke="none" />
      <circle cx="12.7" cy="11" r="1.3" fill="#ff8a00" stroke="none" />
      <path d="M1.5 10v3M18.5 10v3" />
    </g>
  ),
  db: (
    <g>
      <path d="M4 16.5 6.2 3l3.4 6.3L11.4 6 16 16.5 10 19.5Z" fill="#FFA000" />
      <path d="M4 16.5 11.4 6 16 16.5 10 19.5Z" fill="#F57C00" />
      <path d="m4 16.5 6.2-13.5 3.3 6.5Z" fill="#FFCA28" />
    </g>
  ),
  bridge: (
    <g strokeLinecap="round">
      <path d="M4 3v14M10 5v11M16 2v13" stroke="#8c8378" strokeWidth="1.2" />
      <rect x="2.5" y="7" width="3" height="6" rx=".6" fill="#1fa7a0" />
      <rect x="8.5" y="8" width="3" height="5" rx=".6" fill="#e5574b" />
      <rect x="14.5" y="4" width="3" height="8" rx=".6" fill="#1fa7a0" />
    </g>
  ),
  broker: (
    <g fill="none" stroke="#ff8a00" strokeWidth="1.5">
      <rect x="3" y="2.5" width="14" height="6" rx="1.5" />
      <rect x="3" y="11.5" width="14" height="6" rx="1.5" />
      <circle cx="6.5" cy="5.5" r=".9" fill="#1fa7a0" stroke="none" />
      <circle cx="6.5" cy="14.5" r=".9" fill="#1fa7a0" stroke="none" />
      <path d="M10 5.5h4M10 14.5h4" strokeLinecap="round" />
    </g>
  ),
};

const NODES = {
  tg: { x: 70, y: 46, label: 'Telegram', img: telegram },
  app: { x: 290, y: 46, label: 'Mini App', glyph: 'app' },
  bot: { x: 180, y: 128, label: 'AW Bot · API', glyph: 'bot' },
  db: { x: 62, y: 330, label: 'Firestore', glyph: 'db' },
  pay: { x: 298, y: 330, label: 'TON · Pay', img: wallet },
  bridge: { x: 112, y: 420, label: 'MT5 · Wine', glyph: 'bridge' },
  broker: { x: 262, y: 420, label: 'Broker', glyph: 'broker' },
};
const ENGINE = { x: 180, y: 232 };

const EDGES = [
  { id: 'tg-bot', d: 'M70 64 C70 100 150 100 172 112' },
  { id: 'app-bot', d: 'M290 64 C290 100 210 100 188 112' },
  { id: 'bot-eng', d: 'M180 146 L180 188' },
  { id: 'eng-db', d: 'M146 256 C100 280 70 290 64 312' },
  { id: 'eng-pay', d: 'M214 256 C260 280 294 290 296 312' },
  { id: 'eng-bridge', d: 'M168 276 C150 330 120 360 114 402' },
  { id: 'bridge-broker', d: 'M166 420 L210 420' },
  { id: 'pay-bot', d: 'M306 312 C340 230 300 160 214 132' },
];

const mask = () => `***${Math.floor(10 + Math.random() * 89)}`;
const hex = () => Math.random().toString(16).slice(2, 8);
const ms = (a, b) => Math.round(a + Math.random() * (b - a));

// سيناريوهات تشغيل: كل خطوة تُضيء مسارًا وتطبع سطرًا في الطرفية
const RUNS = [
  { wf: 'payment.confirm', steps: () => [
    ['pay-bot', 'trigger', `POST /api/payments/ton-webhook  202`],
    ['bot-eng', 'queue', `webhook_inbox ← ${hex()}  attempt=1`],
    ['eng-pay', 'verify', `toncenter.getTransactions  match=order ✓  ${ms(30, 90)}ms`],
    ['eng-db', 'write', `payments/${mask()} status=finished · subscription +30d`],
    ['tg-bot', 'notify', `telegram.sendMessage chat=${mask()}  200 OK`],
  ] },
  { wf: 'mt5.sync', steps: () => [
    ['bot-eng', 'cron', `sync.tick  due=2  load=ok`],
    ['eng-bridge', 'bridge', `mt5linux.initialize(login=${mask()})  ${ms(600, 1900)}ms`],
    ['bridge-broker', 'fetch', `account_info + history_deals_get  deals=${ms(3, 40)}`],
    ['eng-db', 'write', `users/${mask()} live.balance · report.series  ✓`],
  ] },
  { wf: 'account.link', steps: () => [
    ['app-bot', 'request', `POST /api/register  terms=v2026-09`],
    ['bot-eng', 'guard', `blacklist ✓ duplicate ✓ leverage ✓`],
    ['eng-bridge', 'verify', `mt5.login(server=Exness-*)  ${ms(900, 2400)}ms`],
    ['bridge-broker', 'auth', `broker handshake  OK`],
    ['eng-db', 'write', `users/${mask()} status=approved  sync.state=new`],
  ] },
  { wf: 'rewards.scratch', steps: () => [
    ['app-bot', 'request', `POST /api/scratch/claim`],
    ['bot-eng', 'rng', `SystemRandom.choices(weights=[60,25,10,4,1])`],
    ['eng-db', 'write', `scratch_cards/${mask()} prize sealed · ttl=24h`],
  ] },
  { wf: 'digest.weekly', steps: () => [
    ['bot-eng', 'cron', `digest.run(period=weekly)`],
    ['eng-db', 'read', `users where status=approved  n=${ms(2, 60)}`],
    ['tg-bot', 'notify', `telegram.sendMessage ×${ms(2, 60)}  delivered`],
  ] },
];

const now = () => new Date().toLocaleTimeString('en-GB', { hour12: false }) + '.' + String(Date.now() % 1000).padStart(3, '0');

function Node({ n }) {
  const w = 104;
  return (
    <g className="flow-node" transform={`translate(${n.x - w / 2} ${n.y - 18})`}>
      <rect width={w} height="36" rx="10" />
      {n.img ? <image href={n.img} x="8" y="8" width="20" height="20" /> : <g transform="translate(8 8)">{GLYPH[n.glyph]}</g>}
      <text x="34" y="22">{n.label}</text>
    </g>
  );
}

export default function N8nFlow({ t }) {
  const [live, setLive] = useState([]); // المسارات المضاءة الآن
  const [lines, setLines] = useState([]);
  const termRef = useRef(null);
  const seq = useRef(4800);

  useEffect(() => {
    let cancelled = false;
    let timer;
    let r = 0;
    const push = (line) => setLines((l) => [...l.slice(-13), { ...line, id: `${Date.now()}-${Math.random()}` }]);
    const runOne = () => {
      if (cancelled) return;
      const run = RUNS[r++ % RUNS.length];
      const steps = run.steps();
      const id = (seq.current += 1);
      push({ kind: 'cmd', text: `n8n execute --workflow ${run.wf} #${id}` });
      let i = 0;
      const next = () => {
        if (cancelled) return;
        if (i >= steps.length) {
          push({ kind: 'ok', text: `✓ ${run.wf} #${id} finished  ${steps.length} nodes` });
          setLive([]);
          timer = setTimeout(runOne, 1400);
          return;
        }
        const [edge, tag, text] = steps[i++];
        setLive([edge]);
        push({ kind: 'step', at: now(), tag, text });
        timer = setTimeout(next, 650);
      };
      timer = setTimeout(next, 450);
    };
    runOne();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, []);

  useEffect(() => {
    if (termRef.current) termRef.current.scrollTop = termRef.current.scrollHeight;
  }, [lines]);

  return (
    <div className="section n8n">
      <div className="section-head">
        <h2>{t.anN8n}</h2>
        <span className="tag">{t.anDemo}</span>
      </div>
      <p className="sub">{t.anN8nSub}</p>

      <svg className="flow" viewBox="0 0 360 450" role="img" aria-label={t.anN8n}>
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
          <g key={e.id} className={`flow-edge ${live.includes(e.id) ? 'is-live' : ''}`}>
            <path id={`fe-${e.id}`} d={e.d} className="edge-base" />
            <path d={e.d} className="edge-flow" />
            {live.includes(e.id) && (
              <circle r="3.5" className="edge-pulse">
                <animateMotion dur="0.65s" repeatCount="indefinite">
                  <mpath href={`#fe-${e.id}`} />
                </animateMotion>
              </circle>
            )}
          </g>
        ))}

        <g className={`engine ${live.length ? 'is-busy' : ''}`} transform={`translate(${ENGINE.x} ${ENGINE.y})`}>
          <circle r="78" fill="url(#eng-glow)" className="engine-glow" />
          <circle r="46" className="engine-ring" />
          <image href={light} x="-44" y="-44" width="88" height="88" className="engine-orb" />
          <text y="64" textAnchor="middle" className="engine-label">n8n Engine</text>
        </g>

        {Object.entries(NODES).map(([k, n]) => (
          <Node key={k} n={n} />
        ))}
      </svg>

      <div className="term" dir="ltr">
        <div className="term-bar">
          <i /><i /><i />
          <span>n8n@aw-robot: ~/workflows</span>
        </div>
        <div className="term-body" ref={termRef} aria-live="polite">
          {lines.map((l, idx) => (
            <div key={l.id} className={`term-line is-${l.kind} ${idx === lines.length - 1 ? 'is-typing' : ''}`}>
              {l.kind === 'cmd' && <><b className="t-prompt">$</b> {l.text}</>}
              {l.kind === 'step' && <><span className="t-time">[{l.at}]</span> <span className="t-tag">▸ {l.tag.padEnd(8, ' ')}</span> {l.text}</>}
              {l.kind === 'ok' && <span className="t-ok">{l.text}</span>}
            </div>
          ))}
          <span className="term-cursor" />
        </div>
      </div>
    </div>
  );
}
