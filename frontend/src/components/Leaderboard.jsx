import React, { useEffect, useState } from 'react';
import { getLeaderboard } from '../api';
import { fill } from '../i18n';
import { TIERS } from '../tiers';
import Avatar from './Avatar';
import { fmt } from './Stats';

const tierImg = (key) => TIERS.find((x) => x.key === key)?.img;

function Row({ t, r }) {
  return (
    <li className={`lb-row ${r.you ? 'is-you' : ''}`}>
      <span className="lb-rank" dir="ltr">{r.rank}</span>
      <Avatar kind={r.avatar} size={34} />
      <span className="lb-name">
        <bdi>{r.you ? t.lbYou : r.name}</bdi>
        {r.simulated && <span className="lb-sim">{t.lbSim}</span>}
      </span>
      {r.tier && <img className="lb-tier" src={tierImg(r.tier)} alt="" />}
      <span className={`lb-pct ${r.pct >= 0 ? 'up' : 'down'}`} dir="ltr">
        {r.delta > 0 ? '▲' : r.delta < 0 ? '▼' : ''} {r.pct > 0 ? '+' : ''}{fmt(r.pct)}%
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
      <div className="section-head">
        <h2>{t.lbTitle}</h2>
        <span className="tag live-tag">● {t.lbLive}</span>
      </div>
      {lb.me && (
        <p className="sub">{fill(t.lbYourRank, { rank: lb.me.rank, total: lb.total })}</p>
      )}

      <div className="podium">
        {podium.map((r) => (
          <div key={r.id} className={`pod pod-${r.rank} ${r.you ? 'is-you' : ''}`}>
            <span className="pod-crown">{r.rank === 1 ? '👑' : r.rank}</span>
            <Avatar kind={r.avatar} size={r.rank === 1 ? 64 : 52} />
            <b><bdi>{r.you ? t.lbYou : r.name.split(' ')[0]}</bdi></b>
            <span className="pod-pct" dir="ltr">+{fmt(r.pct)}%</span>
            {r.simulated && <span className="lb-sim">{t.lbSim}</span>}
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
      {lb.has_simulated && <p className="muted small-note">{t.lbSimNote}</p>}
    </div>
  );
}
