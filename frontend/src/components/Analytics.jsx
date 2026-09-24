import React, { useEffect, useMemo, useState } from 'react';
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { getAnalytics } from '../api';
import { fill } from '../i18n';
import { tierFor } from '../tiers';
import { fmt, pct, Row, tone } from './Stats';
import { DashboardSkeleton } from './Skeleton';
import Icon from './Icon';
import N8nFlow from './N8nFlow';
import Leaderboard from './Leaderboard';

// لونا القطبية (ربح/خسارة) — مُتحقَّق منهما لعمى الألوان على خلفية داكنة؛ والاتجاه (فوق/تحت الصفر) يرمّز الإشارة أيضًا
const UP = '#1fa7a0';
const DOWN = '#e5574b';
const LINE = '#ff8a00';
const GRID = 'rgba(255,255,255,0.07)';
const AXIS = { fill: '#8c8378', fontSize: 11 };
const compact = (v) => new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(v);

// عمود بطرف بيانات مستدير 4px ومربّع عند خط الأساس (للقيم السالبة أيضًا)
function PolarBar({ x, y, width, height, value }) {
  if (!height) return null;
  const w = Math.min(width, 24);
  const bx = x + (width - w) / 2;
  const top = Math.min(y, y + height);
  const h = Math.abs(height);
  const r = Math.min(4, h, w / 2);
  const d = value >= 0
    ? `M${bx},${top + h}V${top + r}Q${bx},${top} ${bx + r},${top}H${bx + w - r}Q${bx + w},${top} ${bx + w},${top + r}V${top + h}Z`
    : `M${bx},${top}V${top + h - r}Q${bx},${top + h} ${bx + r},${top + h}H${bx + w - r}Q${bx + w},${top + h} ${bx + w},${top + h - r}V${top}Z`;
  return <path d={d} fill={value >= 0 ? UP : DOWN} />;
}

function ChartTip({ active, payload, label, cur, name }) {
  if (!active || !payload?.length) return null;
  const v = payload[0].value;
  return (
    <div className="chart-tip">
      <span className="muted">{label}</span>
      <b dir="ltr">{fmt(v, 2, true)} {cur}</b>
      <span className="muted">{name}</span>
    </div>
  );
}

// تجميع سلسلة الربح اليومي أسبوعيًا (ISO، يبدأ الاثنين) أو شهريًا
function group(series, mode) {
  const out = new Map();
  for (const { d, pnl } of series || []) {
    const dt = new Date(`${d}T00:00:00Z`);
    let key;
    if (mode === 'month') key = d.slice(0, 7);
    else {
      const day = (dt.getUTCDay() + 6) % 7;
      key = new Date(dt.getTime() - day * 86400000).toISOString().slice(5, 10);
    }
    out.set(key, (out.get(key) || 0) + pnl);
  }
  const rows = [...out.entries()].map(([k, v]) => ({ k, v: Math.round(v * 100) / 100 }));
  return rows.slice(mode === 'month' ? -6 : -12);
}

export default function Analytics({ t, lang, data, onReferral }) {
  const [mode, setMode] = useState('week');
  const [refs, setRefs] = useState(null);
  const { live, subscription: sub } = data;
  const r = data.report || {};

  useEffect(() => {
    getAnalytics().then((x) => setRefs(x.referrals)).catch(() => setRefs(null));
  }, []);

  const bars = useMemo(() => group(r.series, mode), [r.series, mode]);
  const curve = useMemo(() => {
    let acc = 0;
    return (r.series || []).slice(-60).map(({ d, pnl }) => ({ k: d.slice(5), v: Math.round((acc += pnl) * 100) / 100 }));
  }, [r.series]);

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
  const money = (n) => (n == null ? '—' : `${fmt(n)} ${cur}`);
  const linked = refs?.linked ?? 0;
  const tier = tierFor(linked);

  return (
    <section className="dash analytics">
      <h1 className="page-title">{t.anTitle}</h1>

      <div className="kpis">
        <div className="kpi">
          <span className="kpi-label">{t.anTotalProfit}</span>
          <strong className={`kpi-value ${tone(r.total_pnl)}`} dir="ltr">{fmt(r.total_pnl, 2, true)}</strong>
          <span className="kpi-sub" dir="ltr">{cur} · {pct(r.total_growth_pct)}</span>
        </div>
        <div className="kpi">
          <span className="kpi-label">{t.winRate}</span>
          <strong className="kpi-value" dir="ltr">{r.win_rate == null ? '—' : `${fmt(r.win_rate, 1)}%`}</strong>
          <span className="kpi-sub">{t.closedTrades}: <bdi dir="ltr">{r.trades ?? 0}</bdi></span>
        </div>
        <div className="kpi">
          <span className="kpi-label">{t.anReferrals}</span>
          <strong className="kpi-value" dir="ltr">{refs ? linked : '—'}</strong>
          <span className="kpi-sub">{fill(t.anInvited, { n: refs?.invited ?? 0 })}</span>
        </div>
        <div className="kpi">
          <span className="kpi-label">{t.anConversion}</span>
          <strong className="kpi-value" dir="ltr">{refs?.conversion_pct == null ? '—' : `${fmt(refs.conversion_pct, 1)}%`}</strong>
          <span className="kpi-sub">{fill(t.anPaid, { n: refs?.paid ?? 0 })}</span>
        </div>
      </div>

      <div className="section">
        <div className="section-head">
          <h2>{mode === 'week' ? t.anWeekly : t.anMonthly}</h2>
          <div className="seg" role="tablist">
            <button type="button" role="tab" aria-selected={mode === 'week'} className={mode === 'week' ? 'on' : ''} onClick={() => setMode('week')}>{t.week}</button>
            <button type="button" role="tab" aria-selected={mode === 'month'} className={mode === 'month' ? 'on' : ''} onClick={() => setMode('month')}>{t.month}</button>
          </div>
        </div>
        {bars.length === 0 ? (
          <p className="sub">{t.anNoSeries}</p>
        ) : (
          <div className="chart" dir="ltr">
            <ResponsiveContainer width="100%" height={190}>
              <BarChart data={bars} margin={{ top: 8, right: 4, left: 0, bottom: 0 }}>
                <CartesianGrid stroke={GRID} vertical={false} />
                <XAxis dataKey="k" tick={AXIS} axisLine={false} tickLine={false} />
                <YAxis tick={AXIS} axisLine={false} tickLine={false} width={40} tickFormatter={compact} />
                <Tooltip cursor={{ fill: 'rgba(255,255,255,0.04)' }} content={<ChartTip cur={cur} name={t.anPnl} />} />
                <Bar dataKey="v" shape={<PolarBar />} isAnimationActive />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {curve.length > 1 && (
        <div className="section">
          <h2>{t.anCurve}</h2>
          <div className="chart" dir="ltr">
            <ResponsiveContainer width="100%" height={170}>
              <AreaChart data={curve} margin={{ top: 8, right: 4, left: 0, bottom: 0 }}>
                <CartesianGrid stroke={GRID} vertical={false} />
                <XAxis dataKey="k" tick={AXIS} axisLine={false} tickLine={false} minTickGap={28} />
                <YAxis tick={AXIS} axisLine={false} tickLine={false} width={40} tickFormatter={compact} />
                <Tooltip cursor={{ stroke: 'rgba(255,255,255,0.25)' }} content={<ChartTip cur={cur} name={t.anCumulative} />} />
                <Area type="monotone" dataKey="v" stroke={LINE} strokeWidth={2} fill={LINE} fillOpacity={0.1} activeDot={{ r: 4, stroke: '#100e0c', strokeWidth: 2 }} dot={false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      <Leaderboard t={t} />

      <div className="section motivate">
        <img src={tier.cur.img} alt="" className="tier-badge" />
        <div className="motivate-body">
          <h2>{fill(t.anLevel, { tier: t[`tier_${tier.cur.key}`] })}</h2>
          {tier.next ? (
            <>
              <div className="progress"><span style={{ width: `${tier.progress * 100}%` }} /></div>
              <p className="sub">{fill(t.anNextLevel, { n: tier.left, tier: t[`tier_${tier.next.key}`] })}</p>
            </>
          ) : (
            <p className="sub">{t.anTopLevel}</p>
          )}
          {r.weekly_growth_pct > 0 && <p className="sub">{fill(t.anGoodWeek, { p: pct(r.weekly_growth_pct) })}</p>}
          <button type="button" className="btn primary small" onClick={onReferral}>
            <Icon name="share" size={16} />
            <span>{t.anShareCta}</span>
          </button>
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

      <N8nFlow t={t} />
    </section>
  );
}
