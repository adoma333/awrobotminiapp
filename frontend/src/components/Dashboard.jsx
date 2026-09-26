import React from 'react';
import Avatar from './Avatar';
import { fill } from '../i18n';
import { DashboardSkeleton } from './Skeleton';
import { fmt, pct, tone } from './Stats';

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

export default function Dashboard({ t, lang, data, onRenew, onRewards }) {
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
  const ageSecs = live.updated_at ? Date.now() / 1000 - live.updated_at : 0;
  const stale = sync.state === 'error' || ageSecs > 3 * 3600;

  return (
    <section className="dash">
      <div className="who">
        <Avatar kind={avatar || 'boy'} src={data.photo_url} size={44} />
        <div className="who-text">
          <div className="who-name">{nickname}</div>
          <div className="who-meta"><bdi dir="ltr">{account.login} · {account.server}</bdi></div>
        </div>
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

      {(lang === 'ar' ? data.settings?.announcement_ar : data.settings?.announcement_en) && (
        <div className="note announce" role="status">{lang === 'ar' ? data.settings.announcement_ar : data.settings.announcement_en}</div>
      )}

      {/* بطاقة كشط جديدة تأخذ مكان تنبيه «التداول غير مفعّل» حتى لا تتكدّس المستطيلات */}
      {!sub?.active && !(data.scratch_pending > 0) && (
        <div className="note warn sub-note" role="status">
          <span>{sub ? t.subExpired : t.subNone}</span>
          <button type="button" className="btn soft small" onClick={onRenew}><span>{sub ? t.renew : t.subscribe}</span></button>
        </div>
      )}
      {sub && sub.active && sub.days_left <= 5 && (
        <div className="note sub-note" role="status">
          <span>{fill(t.subEnding, { n: sub.days_left })}</span>
          <button type="button" className="btn soft small" onClick={onRenew}><span>{t.renew}</span></button>
        </div>
      )}

      {data.scratch_pending > 0 && (
        <div className="note sub-note scratch-banner" role="status">
          <span>{t.rwBanner}</span>
          <button type="button" className="btn primary small" onClick={onRewards}><span>{t.rwOpen}</span></button>
        </div>
      )}

      {stale && <p className="note warn" role="status">{t.staleWarn}</p>}

      <div className="section">
        <h2>{t.growth}</h2>
        <div className="grid2 growth-grid">
          <Cell label={t.today} pctValue={r.daily_growth_pct} money={r.daily_pnl} cur={cur} />
          <Cell label={t.week} pctValue={r.weekly_growth_pct} money={r.weekly_pnl} cur={cur} />
          <Cell label={t.month} pctValue={r.monthly_growth_pct} money={r.monthly_pnl} cur={cur} />
          <Cell label={t.allTime} pctValue={r.total_growth_pct} money={r.total_pnl} cur={cur} />
        </div>
      </div>

    </section>
  );
}
