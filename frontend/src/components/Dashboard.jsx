import React, { useMemo, useState } from 'react';
import Avatar from './Avatar';
import Icon from './Icon';
import { fill } from '../i18n';
import { haptic } from '../telegram';
import { openSupport } from '../support';
import { DashboardSkeleton } from './Skeleton';
import { FeedbackCard } from './FeedbackButton';
import { fmt, pct, tone } from './Stats';

const HIDE_KEY = 'aw_hide_balance';
const MASK = '••••••';

function Cell({ label, pctValue, money, cur, hidden }) {
  return (
    <div className="cell">
      <span className="cell-label">{label}</span>
      <strong className={`cell-value ${tone(pctValue)}`} dir="ltr">
        {pct(pctValue)}
      </strong>
      <span className="cell-sub" dir="ltr">
        {hidden ? MASK : `${fmt(money, 2, true)} ${cur}`}
      </span>
    </div>
  );
}

// منحنى الأرباح التراكمي (آخر 30 يومًا) داخل بطاقة الرصيد
function Spark({ series }) {
  const d = useMemo(() => {
    const pts = (series || []).slice(-30);
    if (pts.length < 2) return null;
    let acc = 0;
    const ys = pts.map((p) => (acc += Number(p.pnl) || 0));
    const lo = Math.min(0, ...ys);
    const hi = Math.max(...ys, lo + 1);
    const W = 300;
    const H = 56;
    const xy = ys.map((y, i) => [(i / (ys.length - 1)) * W, H - 4 - ((y - lo) / (hi - lo)) * (H - 8)]);
    const line = xy.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join('');
    return { line, area: `${line}L${W},${H}L0,${H}Z`, up: ys[ys.length - 1] >= 0 };
  }, [series]);
  if (!d) return null;
  return (
    <svg className={`hero-spark ${d.up ? 'is-up' : 'is-down'}`} viewBox="0 0 300 56" preserveAspectRatio="none" aria-hidden="true">
      <defs>
        <linearGradient id="spk" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="currentColor" stopOpacity="0.35" />
          <stop offset="100%" stopColor="currentColor" stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={d.area} fill="url(#spk)" />
      <path d={d.line} fill="none" stroke="currentColor" strokeWidth="2" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export default function Dashboard({ t, lang, data, onRenew, onRewards, onReferral }) {
  const { live, nickname, avatar, subscription: sub } = data;
  const r = data.report || {};
  const sync = data.sync || {};
  const account = data.account || {};
  const [hidden, setHidden] = useState(() => {
    try {
      return localStorage.getItem(HIDE_KEY) === '1';
    } catch {
      return false;
    }
  });

  if (!live) {
    return (
      <>
        <p className="sync-note" role="status">{t.firstSync} — {t.firstSyncSub}</p>
        <DashboardSkeleton />
      </>
    );
  }

  function toggleHidden() {
    haptic.select();
    const v = !hidden;
    setHidden(v);
    try {
      localStorage.setItem(HIDE_KEY, v ? '1' : '0');
    } catch {
      /* تخزين غير متاح */
    }
  }

  const cur = live.currency || '';
  const ageSecs = live.updated_at ? Date.now() / 1000 - live.updated_at : 0;
  const stale = sync.state === 'error' || ageSecs > 3 * 3600;
  const money = (v, sign) => (hidden ? MASK : fmt(v, 2, sign));
  const scratch = data.scratch_pending > 0;
  const subPct = sub?.active ? Math.max(4, Math.min(100, ((sub.days_left || 0) / 30) * 100)) : 0;

  return (
    <section className="dash">
      <div className="who">
        <Avatar kind={avatar || 'boy'} src={data.photo_url} size={44} />
        <div className="who-text">
          <div className="who-name">{nickname}</div>
          <div className="who-meta"><bdi dir="ltr">{account.login} · {account.server}</bdi></div>
        </div>
        <span className={`live-dot ${stale ? 'is-stale' : ''}`} title={stale ? t.staleWarn : ''} aria-hidden="true" />
      </div>

      <FeedbackCard t={t} lang={lang} />

      <div className="hero hero-card">
        <div className="hero-top">
          <span className="row-label">{t.balance}</span>
          <button type="button" className="eye-btn" aria-pressed={hidden} aria-label={hidden ? t.balShow : t.balHide} title={hidden ? t.balShow : t.balHide} onClick={toggleHidden}>
            <Icon name={hidden ? 'eyeOff' : 'eye'} size={19} />
          </button>
        </div>
        <div className={`hero-num ${hidden ? 'is-hidden' : ''}`} dir="ltr">
          <span>{hidden ? MASK : fmt(live.balance)}</span>
          <small>{cur}</small>
        </div>
        <div className="hero-sub">
          <span className={`chip ${tone(r.total_growth_pct)}`} dir="ltr">{pct(r.total_growth_pct)}</span>
          <span className="muted">{t.allTime}</span>
          {r.daily_pnl != null && (
            <span className={`hero-today ${tone(r.daily_pnl)}`} dir="ltr">{money(r.daily_pnl, true)} <small>{t.today}</small></span>
          )}
        </div>
        <Spark series={r.series} />
        <div className="hero-stats">
          <div><span>{t.equity}</span><b dir="ltr">{money(live.equity)}</b></div>
          <div><span>{t.floating}</span><b dir="ltr" className={tone(live.profit)}>{money(live.profit, true)}</b></div>
          <div><span>{t.marginLevel}</span><b dir="ltr">{live.margin_level ? `${fmt(live.margin_level, 0)}%` : '—'}</b></div>
        </div>
      </div>

      {(lang === 'ar' ? data.settings?.announcement_ar : data.settings?.announcement_en) && (
        <div className="note announce" role="status">{lang === 'ar' ? data.settings.announcement_ar : data.settings.announcement_en}</div>
      )}

      {/* بطاقة كشط جديدة تأخذ مكان تنبيه «التداول الآلي غير مفعّل» حتى لا تتكدّس المستطيلات */}
      {!sub?.active && !scratch && (
        <div className="note warn sub-note" role="status">
          <span>{sub ? t.subExpired : t.subNone}</span>
          <button type="button" className="btn soft small" onClick={onRenew}><span>{sub ? t.renew : t.subscribe}</span></button>
        </div>
      )}
      {sub?.active && (
        <button type="button" className={`sub-card ${sub.days_left <= 5 ? 'is-ending' : ''}`} onClick={onRenew}>
          <div className="sub-card-top">
            <span><Icon name="bolt" size={16} /> {lang === 'ar' ? sub.package_name_ar || t.subActive : sub.package_name_en || t.subActive}</span>
            <b dir="ltr">{fill(t.subDaysLeft, { n: sub.days_left ?? 0 })}</b>
          </div>
          <span className="sub-bar"><i style={{ width: `${subPct}%` }} /></span>
          {sub.days_left <= 5 && <small>{fill(t.subEnding, { n: sub.days_left })} · {t.renew}</small>}
        </button>
      )}

      {scratch && (
        <div className="note sub-note scratch-banner" role="status">
          <span>{t.rwBanner}</span>
          <button type="button" className="btn primary small" onClick={onRewards}><span>{t.rwOpen}</span></button>
        </div>
      )}

      <div className="quick-grid">
        {[
          ['plans', t.navPlans, onRenew],
          ['rewards', t.navRewards, onRewards, data.scratch_pending],
          ['referral', t.navReferral, onReferral],
          ['headset', t.supportOpen, () => openSupport()],
        ].map(([ic, label, fn, badge]) => (
          <button key={ic} type="button" className="quick" onClick={() => { haptic.select(); fn?.(); }}>
            <span className="quick-ic"><Icon name={ic} size={22} />{badge > 0 && <em>{badge}</em>}</span>
            <span>{label}</span>
          </button>
        ))}
      </div>

      {stale && <p className="note warn" role="status">{t.staleWarn}</p>}

      <div className="section">
        <h2>{t.growth}</h2>
        <div className="grid2 growth-grid">
          <Cell label={t.today} pctValue={r.daily_growth_pct} money={r.daily_pnl} cur={cur} hidden={hidden} />
          <Cell label={t.week} pctValue={r.weekly_growth_pct} money={r.weekly_pnl} cur={cur} hidden={hidden} />
          <Cell label={t.month} pctValue={r.monthly_growth_pct} money={r.monthly_pnl} cur={cur} hidden={hidden} />
          <Cell label={t.allTime} pctValue={r.total_growth_pct} money={r.total_pnl} cur={cur} hidden={hidden} />
        </div>
      </div>
    </section>
  );
}
