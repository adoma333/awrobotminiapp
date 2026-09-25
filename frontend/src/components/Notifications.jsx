import React, { useEffect, useState } from 'react';
import PageHead from './PageHead';
import Icon from './Icon';
import { getNotifications, markNotificationsRead } from '../api';
import { timeAgo } from '../format';

const KIND_ICON = { payment: 'card', deposit: 'wallet', trade: 'chart', security: 'lock', account: 'user', support: 'headset', system: 'bell', broadcast: 'megaphone' };

/** مركز الإشعارات: الواردة تلقائيًا من نشاط الحساب + رسائل الأدمن، محفوظة كسجل. */
export default function Notifications({ t, lang, onBack, onRead }) {
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    getNotifications()
      .then((d) => {
        if (!alive) return;
        setData(d);
        if (d.unread) markNotificationsRead().then(() => onRead?.()).catch(() => {});
      })
      .catch(() => alive && setFailed(true));
    return () => {
      alive = false;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const items = data?.items || [];
  return (
    <section className="dash">
      <PageHead t={t} title={t.notifTitle} onBack={onBack} />
      {failed && <p className="note warn">{t.notifErr}</p>}
      {!data && !failed && <div className="notif-skel" aria-hidden="true"><span /><span /><span /></div>}
      {data && items.length === 0 && (
        <div className="notif-empty">
          <span className="notif-empty-ic"><Icon name="bell" size={28} /></span>
          <b>{t.notifEmpty}</b>
          <p className="muted">{t.notifEmptySub}</p>
        </div>
      )}
      <ul className="notif-list">
        {items.map((n) => (
          <li key={n.id} className={`notif-item kind-${n.kind} ${n.unread ? 'is-unread' : ''}`}>
            <span className="notif-ic"><Icon name={KIND_ICON[n.kind] || 'bell'} size={19} /></span>
            <div className="notif-body">
              <div className="notif-top">
                <b>{n[`title_${lang}`] || n.title_en || n.title_ar}</b>
                <time>{timeAgo(n.at, lang)}</time>
              </div>
              {(n[`body_${lang}`] || n.body_en || n.body_ar) && <p>{n[`body_${lang}`] || n.body_en || n.body_ar}</p>}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
