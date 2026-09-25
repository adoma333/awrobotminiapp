import React, { useCallback, useEffect, useState } from 'react';
import PageHead from './PageHead';
import ErrorNote from './ErrorNote';
import { getRewards, redeemReward } from '../api';
import { haptic, requestContact } from '../telegram';
import { CHECKOUT_TYPES, countdown, prizeIcon, prizeLabel } from '../rewards';
import ScratchCard from './ScratchCard';
import Icon from './Icon';
import AnimIcon from './AnimIcon';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const STATUS = { active: 'rwActive', used: 'rwUsed', expired: 'rwExpired' };

/** محفظة المكافآت: بطاقات تنتظر الكشف + الجوائز المكتسبة (النوع، القيمة، الانتهاء، الاستخدام). */
export default function RewardsHub({ t, onBack, onUse, onRedeemed }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(false);
  const [active, setActive] = useState(null); // بطاقة قيد الخدش
  const [needPhone, setNeedPhone] = useState(false);
  const [phoneBusy, setPhoneBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const [now, setNow] = useState(Date.now() / 1000);

  const load = useCallback(() => {
    setError(false);
    return getRewards()
      .then((r) => {
        setData(r);
        return r;
      })
      .catch(() => setError(true));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(id);
  }, []);

  async function verifyPhone() {
    setPhoneBusy(true);
    setMsg('');
    const shared = await requestContact();
    if (shared) {
      // الرقم يصل للبوت عبر webhook: ننتظر تأكيد الخادم
      for (let i = 0; i < 8; i += 1) {
        await sleep(1500);
        const r = await getRewards().catch(() => null);
        if (r?.phone_verified) {
          setData(r);
          setNeedPhone(false);
          setPhoneBusy(false);
          setActive(r.cards[0]?.id || null);
          return;
        }
      }
    }
    haptic.error();
    setMsg('rwPhoneFail');
    setPhoneBusy(false);
  }

  async function use(r) {
    setMsg('');
    if (CHECKOUT_TYPES.includes(r.type)) return onUse(r.id);
    if (r.type === 'free_month') {
      try {
        await redeemReward(r.id);
        haptic.success();
        setMsg('rwRedeemed');
        load();
        onRedeemed?.();
      } catch {
        haptic.error();
        setMsg('rwUseErr');
        load();
      }
    }
    return undefined;
  }

  const cards = data?.cards || [];
  const list = data?.rewards || [];

  return (
    <section className="dash">
      <PageHead t={t} title={t.rwTitle} onBack={onBack} />

      {error && <ErrorNote t={t} kind="operation" code="rewards_load_failed">{t.rwErr}</ErrorNote>}
      {!error && !data && <div className="loader" role="status" aria-label={t.loading} />}

      {needPhone && (
        <div className="section">
          <h2>{t.rwPhoneTitle}</h2>
          <p className="sub">{t.rwPhoneBody}</p>
          <div className="actions inline">
            <button type="button" className="btn primary" disabled={phoneBusy} onClick={verifyPhone}>
              <span>{phoneBusy ? t.rwPhoneWait : t.rwPhoneBtn}</span>
            </button>
          </div>
        </div>
      )}

      {active && !needPhone && (
        <div className="section">
          <h2>{t.rwScratchTitle}</h2>
          <ScratchCard
            key={active}
            t={t}
            cardId={active}
            onNeedPhone={() => setNeedPhone(true)}
            onRevealed={() => load()}
          />
          <div className="actions inline">
            <button type="button" className="btn ghost small" onClick={() => setActive(null)}>
              <span>{t.close}</span>
            </button>
          </div>
        </div>
      )}

      {data && cards.length > 0 && !active && (
        <div className="section">
          <h2>{t.rwCards}</h2>
          <div className="rows">
            {cards.map((c) => (
              <button type="button" key={c.id} className="row row-link scratch-row" onClick={() => setActive(c.id)}>
                <span className="row-label row-icon"><Icon name="rewards" size={18} /> {t[`rwEvent_${c.event.split('_')[0]}`] || t.rwEvent_welcome}</span>
                <span className="btn soft small"><span>{t.rwScratchCta}</span></span>
              </button>
            ))}
          </div>
        </div>
      )}

      {data && (
        <div className="section">
          <h2>{t.rwMine}</h2>
          {list.length === 0 && <p className="sub">{t.rwEmpty}</p>}
          <div className="reward-list">
            {list.map((r) => (
              <article key={r.id} className={`reward is-${r.status}`}>
                <AnimIcon className="reward-icon" name={r.type} src={prizeIcon(r.type)} />
                <div className="reward-body">
                  <strong>{prizeLabel(t, r)}</strong>
                  <span className="muted">
                    {r.status === 'active' ? <span className="countdown">⏱ {countdown(t, r.expires_at, now)}</span> : t[STATUS[r.status]]}
                  </span>
                </div>
                {r.status === 'active' && (CHECKOUT_TYPES.includes(r.type) || r.type === 'free_month') && (
                  <button type="button" className="btn primary small" onClick={() => use(r)}>
                    <span>{t.rwUse}</span>
                  </button>
                )}
                {r.status === 'active' && !CHECKOUT_TYPES.includes(r.type) && r.type !== 'free_month' && (
                  <span className="muted small-note">{t.rwManual}</span>
                )}
              </article>
            ))}
          </div>
          <p className="sub small-note">{t.rwHowTo}</p>
        </div>
      )}

      {msg && <p className={msg === 'rwRedeemed' ? 'note' : 'banner-error'} role="status">{t[msg]}</p>}
    </section>
  );
}
