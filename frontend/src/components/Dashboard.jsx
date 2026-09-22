import React from 'react';
import Avatar from './Avatar';
import { fill } from '../i18n';
import { DashboardSkeleton } from './Skeleton';

// الأرقام لاتينية دائمًا (كما في MT5) حتى في الواجهة العربية
const fmt = (n, d = 2, sign = false) =>
  n == null || Number.isNaN(n)
    ? '—'
    : new Intl.NumberFormat('en-US', {
        minimumFractionDigits: d,
        maximumFractionDigits: d,
        signDisplay: sign ? 'exceptZero' : 'auto',
      }).format(n);

const pct = (n) => (n == null ? '—' : `${fmt(n, 2, true)}%`);
const tone = (n) => (n == null || n === 0 ? 'flat' : n > 0 ? 'up' : 'down');

function timeAgo(epoch, lang) {
  if (!epoch) return '—';
  const secs = Math.max(0, Math.round(Date.now() / 1000 - epoch));
  const rtf = new Intl.RelativeTimeFormat(lang === 'ar' ? 'ar-u-nu-latn' : 'en', { numeric: 'auto' });
  if (secs < 60) return rtf.format(0, 'second');
  if (secs < 3600) return rtf.format(-Math.round(secs / 60), 'minute');
  if (secs < 86400) return rtf.format(-Math.round(secs / 3600), 'hour');
  return rtf.format(-Math.round(secs / 86400), 'day');
}

function Row({ label, value, kind, hint, plain }) {
  return (
    <div className="row">
      <span className="row-label">
        {label}
        {hint && <small>{hint}</small>}
      </span>
      <span className={`row-value ${kind || ''}`} dir={plain ? undefined : 'ltr'}>
        {value}
      </span>
    </div>
  );
}

function Cell({ label, pctValue, money, cur }) {
  return (
    <div className="cell">
      <span className="cell-label">{label}</span>
      <strong className={`cell-value ${tone(pctValue)}`} dir="ltr">
        {pct(pctValue)}
      </strong>
      <span className="cell-sub" dir="ltr">
        {fmt(money, 2, true)} {cur}
      </span>
    </div>
  );
}

export default function Dashboard({ t, lang, data, onRenew, onSettings }) {
  const { live, nickname, avatar, subscription: sub } = data;
  const r = data.report || {};
  const sync = data.sync || {};
  const account = data.account || {};

  if (!live) {
    return (
      <>
        <p className="sync-note" role="status">{t.firstSync} — {t.firstSyncSub}</p>
        <DashboardSkeleton />
      </>
    );
  }

  const cur = live.currency || '';
  const closed = (r.wins || 0) + (r.losses || 0);
  const winShare = closed ? (r.wins / closed) * 100 : 0;
  const ageSecs = live.updated_at ? Date.now() / 1000 - live.updated_at : 0;
  const stale = sync.state === 'error' || ageSecs > 3 * 3600;
  const money = (n) => (n == null ? '—' : `${fmt(n)} ${cur}`);

  return (
    <section className="dash">
      <div className="who">
        <Avatar kind={avatar || 'boy'} size={44} />
        <div className="who-text">
          <div className="who-name">{nickname}</div>
          <div className="who-meta"><bdi dir="ltr">{account.login} · {account.server}</bdi></div>
        </div>
        <button type="button" className="icon-btn" onClick={onSettings} aria-label={t.settingsTitle}>
          <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
          </svg>
        </button>
      </div>

      <div className="hero">
        <span className="row-label">{t.balance}</span>
        <div className="hero-num" dir="ltr">
          <span>{fmt(live.balance)}</span>
          <small>{cur}</small>
        </div>
        <div className="hero-sub">
          <span className={`chip ${tone(r.total_growth_pct)}`} dir="ltr">{pct(r.total_growth_pct)}</span>
          <span className="muted">{t.allTime}</span>
        </div>
      </div>

      {sub && !sub.active && (
        <div className="note warn sub-note" role="status">
          <span>{t.subExpired}</span>
          <button type="button" className="btn soft small" onClick={onRenew}><span>{t.renew}</span></button>
        </div>
      )}
      {sub && sub.active && sub.days_left <= 5 && (
        <div className="note sub-note" role="status">
          <span>{fill(t.subEnding, { n: sub.days_left })}</span>
          <button type="button" className="btn soft small" onClick={onRenew}><span>{t.renew}</span></button>
        </div>
      )}

      {stale && <p className="note warn" role="status">{t.staleWarn}</p>}

      <div className="section">
        <h2>{t.growth}</h2>
        <div className="grid2">
          <Cell label={t.today} pctValue={r.daily_growth_pct} money={r.daily_pnl} cur={cur} />
          <Cell label={t.week} pctValue={r.weekly_growth_pct} money={r.weekly_pnl} cur={cur} />
          <Cell label={t.month} pctValue={r.monthly_growth_pct} money={r.monthly_pnl} cur={cur} />
          <Cell label={t.allTime} pctValue={r.total_growth_pct} money={r.total_pnl} cur={cur} />
        </div>
      </div>

      <div className="section">
        <h2>{t.winRate}</h2>
        <div className="winrate">
          <strong dir="ltr">{r.win_rate == null ? '—' : `${fmt(r.win_rate)}%`}</strong>
          <span className="muted">{t.closedTrades}: <span dir="ltr">{r.trades ?? 0}</span></span>
        </div>
        <div className="bar" role="img" aria-label={`${r.wins} / ${r.losses}`}>
          <span className="bar-win" style={{ width: `${winShare}%` }} />
          <span className="bar-loss" style={{ width: `${closed ? 100 - winShare : 0}%` }} />
        </div>
        <div className="bar-legend">
          <span><i className="dot up" />{t.winsLabel} <b dir="ltr">{r.wins ?? 0}</b></span>
          <span><i className="dot down" />{t.lossesLabel} <b dir="ltr">{r.losses ?? 0}</b></span>
        </div>
      </div>

      <div className="section">
        <h2>{t.performance}</h2>
        <div className="rows">
          <Row label={t.profitFactor} value={fmt(r.profit_factor)} />
          <Row label={t.payoff} value={fmt(r.payoff_ratio)} />
          <Row label={t.expectancy} value={r.expectancy == null ? '—' : `${fmt(r.expectancy, 2, true)} ${cur}`} kind={tone(r.expectancy)} />
          <Row label={t.avgWin} value={money(r.avg_win)} kind="up" />
          <Row label={t.avgLoss} value={r.avg_loss == null ? '—' : `-${fmt(r.avg_loss)} ${cur}`} kind="down" />
          <Row label={t.bestTrade} value={r.best_trade == null ? '—' : `${fmt(r.best_trade, 2, true)} ${cur}`} kind="up" />
          <Row label={t.worstTrade} value={r.worst_trade == null ? '—' : `${fmt(r.worst_trade, 2, true)} ${cur}`} kind="down" />
          <Row label={t.grossProfit} value={money(r.gross_profit)} />
          <Row label={t.grossLoss} value={r.gross_loss == null ? '—' : `-${fmt(r.gross_loss)} ${cur}`} />
          <Row
            label={t.maxDd}
            hint={t.ddNote}
            value={r.max_drawdown == null ? '—' : `${fmt(r.max_drawdown)} ${cur} · ${fmt(r.max_drawdown_pct)}%`}
            kind={r.max_drawdown ? 'down' : ''}
          />
        </div>
      </div>

      <div className="section">
        <h2>{t.accountSection}</h2>
        <div className="rows">
          <Row label={t.equity} value={money(live.equity)} />
          <Row label={t.floating} value={`${fmt(live.profit, 2, true)} ${cur}`} kind={tone(live.profit)} />
          <Row label={t.freeMargin} value={money(live.margin_free)} />
          <Row label={t.marginUsed} value={money(live.margin)} />
          <Row label={t.marginLevel} value={live.margin ? `${fmt(live.margin_level)}%` : '—'} />
          <Row label={t.leverage} value={live.leverage ? `1:${live.leverage}` : '—'} />
          <Row label={t.netDeposits} value={money(r.net_deposits)} />
          {sub && <Row plain label={t.plan} value={`${(lang === 'ar' ? sub.package_name_ar : sub.package_name_en) || '—'} · ${sub.active ? fill(t.daysLeft, { n: sub.days_left }) : t.subExpired}`} />}
        </div>
      </div>

      <p className="foot">
        <i className={`dot ${stale ? 'warn' : 'up'}`} />
        {t.updated}: {timeAgo(live.updated_at, lang)} · {t.syncNote}
      </p>
    </section>
  );
}
