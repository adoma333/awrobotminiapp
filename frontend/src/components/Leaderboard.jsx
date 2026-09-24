import React, { useEffect, useState } from 'react';
import { getLeaderboard } from '../api';
import { fill } from '../i18n';
import { TIERS } from '../tiers';
import Avatar from './Avatar';
import Icon from './Icon';

const usd = (n) => `$${new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 }).format(Math.abs(n))}`;
const signed = (n) => `${n < 0 ? '−' : '+'}${usd(n)}`;
// علامة صغيرة للمنافس المحاكاة (مع سطر توضيحي أسفل القائمة)
const SimMark = ({ t }) => (
  <span className="lb-sim" title={t.lbSimTitle} aria-label={t.lbSimTitle}><Icon name="bolt" size={11} /></span>
);

const tierImg = (key) => TIERS.find((x) => x.key === key)?.img;

function Row({ t, r }) {
  return (
    <li className={`lb-row ${r.you ? 'is-you' : ''}`}>
      <span className="lb-rank" dir="ltr">{r.rank}</span>
      <Avatar kind={r.avatar} size={34} />
      <span className="lb-name">
        <bdi>{r.you ? t.lbYou : r.name}</bdi>
        {r.simulated && <SimMark t={t} />}
      </span>
      {r.tier && <img className="lb-tier" src={tierImg(r.tier)} alt="" />}
      <span className={`lb-pct ${r.usd >= 0 ? 'up' : 'down'}`} dir="ltr">
        {r.delta > 0 ? '▲' : r.delta < 0 ? '▼' : ''} {signed(r.usd)}
      </span>
    </li>
  );
}

/** ترتيب أرباح هذا الأسبوع: منصة التتويج لأول ثلاثة + القائمة + ترتيبك الفعلي. */
export default function Leaderboard({ t }) {
  const [lb, setLb] = useState(null);

  useEffect(() => {
    const load = () => getLeaderboard().then(setLb).catch(() => {});
    load();
    const id = setInterval(load, 60000);
    return () => clearInterval(id);
  }, []);

  if (!lb || !lb.rows.length) return null;
  const top = lb.rows.slice(0, 3);
  const podium = [top[1], top[0], top[2]].filter(Boolean);
  const meVisible = lb.rows.some((r) => r.you);

  return (
    <div className="section leaderboard">
      <h2>{t.lbTitle}</h2>
      {lb.me && (
        <p className="sub">{fill(t.lbYourRank, { rank: lb.me.rank, total: lb.total })}</p>
      )}

      <div className="podium">
        {podium.map((r) => (
          <div key={r.id} className={`pod pod-${r.rank} ${r.you ? 'is-you' : ''}`}>
            <span className="pod-crown">{r.rank === 1 ? '👑' : r.rank}</span>
            <Avatar kind={r.avatar} size={r.rank === 1 ? 64 : 52} />
            <b><bdi>{r.you ? t.lbYou : r.name.split(' ')[0]}</bdi></b>
            <span className="pod-pct" dir="ltr">{signed(r.usd)}</span>
            {r.simulated && <SimMark t={t} />}
            <span className="pod-base" />
          </div>
        ))}
      </div>

      <ol className="lb-list">
        {lb.rows.slice(3).map((r) => <Row key={r.id} t={t} r={r} />)}
      </ol>
      {lb.me && !meVisible && (
        <ol className="lb-list lb-me">
          <Row t={t} r={lb.me} />
        </ol>
      )}
      {lb.has_simulated && (
        <p className="muted small-note lb-legend"><SimMark t={t} /> {t.lbSimNote}</p>
      )}
    </div>
  );
}
