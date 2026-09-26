import React, { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";

export const PRIZE_LABEL = {
  discount: "خصم على الاشتراك (%)",
  free_days: "أيام مجانية",
  slippage_insurance: "رصيد تداول / تأمين انزلاق ($)",
  free_month: "اشتراك مجاني (أيام)",
  funded_challenge: "تحدي حساب ممول ($)",
};
const TRIGGER_LABEL = {
  welcome: "بطاقة الترحيب (إكمال التعريف أو ربط حساب تجريبي)",
  link_real: "ربط حساب حقيقي",
  referral: "إحالة صديق يربط حسابه",
  streak7: "سلسلة تداول متتالية (الطول قابل للتعديل أدناه)",
  first_payment: "أول اشتراك مدفوع",
  renewal: "كل تجديد اشتراك",
};
const STATE_LABEL = { new: "لم تُكشف", active: "صالحة", used: "مستخدمة", expired: "منتهية" };
const STATE_BADGE = { new: "pending", active: "approved", used: "neutral", expired: "rejected" };

function fmtTime(ts) {
  return ts ? new Date(ts * 1000).toLocaleString("en-GB", { dateStyle: "short", timeStyle: "short" }) : "—";
}

/** التحكم الكامل بنظام الخدش: التشغيل، المحفزات، الصلاحية، التأهل، جدول الجوائز والاحتمالات، والكوبونات. */
export default function Rewards() {
  const [cfg, setCfg] = useState(null);
  const [saved, setSaved] = useState(null);
  const [msg, setMsg] = useState("");
  const [cards, setCards] = useState(null);
  const [uidFilter, setUidFilter] = useState("");
  const [grant, setGrant] = useState({ uid: "", type: "", value: "", hours: 24, notify: true });

  const load = useCallback(() => {
    api.rewardsConfig().then((c) => { setCfg(c); setSaved(JSON.stringify(c)); }).catch(() => setMsg("تعذّر تحميل الإعدادات."));
  }, []);
  const loadCards = useCallback(() => {
    api.rewardCards(uidFilter.trim()).then(setCards).catch(() => setCards({ cards: [], stats: null }));
  }, [uidFilter]);
  useEffect(load, [load]);
  useEffect(() => { const t = setTimeout(loadCards, 250); return () => clearTimeout(t); }, [loadCards]);

  const totalWeight = useMemo(
    () => (cfg?.prizes || []).filter((p) => p.enabled).reduce((a, p) => a + (Number(p.weight) || 0), 0),
    [cfg]
  );
  const dirty = cfg && JSON.stringify(cfg) !== saved;

  const setPrize = (i, patch) => setCfg((c) => ({ ...c, prizes: c.prizes.map((p, j) => (j === i ? { ...p, ...patch } : p)) }));

  async function save() {
    setMsg("");
    try {
      const c = await api.saveRewardsConfig({
        ...cfg,
        prizes: cfg.prizes.map((p) => ({ ...p, value: Number(p.value), weight: Number(p.weight) })),
        trigger_prizes: Object.fromEntries(Object.entries(cfg.trigger_prizes || {}).map(([k, rows]) => [k, rows.map((p) => ({ ...p, value: Number(p.value), weight: Number(p.weight) }))])),
        streak_days: Number(cfg.streak_days) || 7,
        max_pending: Number(cfg.max_pending) || 5,
      });
      setCfg(c);
      setSaved(JSON.stringify(c));
      setMsg("✅ تم الحفظ");
    } catch (e) {
      setMsg(`❌ ${e.detail || "تعذّر الحفظ"}`);
    }
  }

  async function doGrant(e) {
    e.preventDefault();
    setMsg("");
    try {
      const body = { uid: grant.uid.trim(), hours: Number(grant.hours) || 24, notify: grant.notify };
      if (grant.type) Object.assign(body, { type: grant.type, value: Number(grant.value) });
      const r = await api.grantReward(body);
      setMsg(r.card_id ? `✅ مُنحت: ${r.card_id}` : "⚠️ لم تُمنح (مكررة)");
      setGrant((g) => ({ ...g, value: "" }));
      loadCards();
    } catch (err) {
      setMsg(`❌ ${err.detail || "تعذّر المنح"}`);
    }
  }

  async function act(fn) {
    try { await fn(); loadCards(); } catch (err) { setMsg(`❌ ${err.detail || "فشل الإجراء"}`); }
  }

  if (!cfg) return <p>{msg || "...جارٍ التحميل"}</p>;
  const st = cards?.stats;

  return (
    <>
      <div className="topbar">
        <h1>المكافآت والكوبونات</h1>
        <div className="row-gap">
          {msg && <span className="muted">{msg}</span>}
          <button className="primary" disabled={!dirty} onClick={save}>حفظ الإعدادات</button>
        </div>
      </div>

      {st && (
        <div className="stat-row">
          <div className="stat"><b>{st.total}</b><span>كل البطاقات</span></div>
          <div className="stat"><b>{st.new}</b><span>لم تُكشف</span></div>
          <div className="stat"><b>{st.active}</b><span>صالحة</span></div>
          <div className="stat"><b>{st.used}</b><span>مستخدمة</span></div>
          <div className="stat"><b>{st.expired}</b><span>منتهية</span></div>
        </div>
      )}

      <div className="panel">
        <h2>التشغيل العام</h2>
        <label className="check"><input type="checkbox" checked={cfg.enabled} onChange={(e) => setCfg({ ...cfg, enabled: e.target.checked })} /> نظام الخدش والمكافآت مفعّل</label>
        <label className="check"><input type="checkbox" checked={cfg.require_phone} onChange={(e) => setCfg({ ...cfg, require_phone: e.target.checked })} /> اشتراط توثيق الهاتف (أو Telegram Premium) لكشف البطاقات</label>
        <div className="field-row">
          <label>صلاحية الجائزة بعد الكشف (ساعات، 1–72)</label>
          <input className="mono narrow" type="number" min="1" max="72" value={cfg.ttl_hours} onChange={(e) => setCfg({ ...cfg, ttl_hours: Number(e.target.value) })} />
        </div>
        <div className="field-row">
          <label>طول سلسلة التداول (أيام عمل، 3–30)</label>
          <input className="mono narrow" type="number" min="3" max="30" value={cfg.streak_days ?? 7} onChange={(e) => setCfg({ ...cfg, streak_days: e.target.value })} />
        </div>
        <div className="field-row">
          <label>أقصى بطاقات غير مكشوفة للمستخدم (1–20)</label>
          <input className="mono narrow" type="number" min="1" max="20" value={cfg.max_pending ?? 5} onChange={(e) => setCfg({ ...cfg, max_pending: e.target.value })} />
        </div>
        <h3>محفزات منح البطاقات</h3>
        {Object.keys(TRIGGER_LABEL).map((k) => {
          const own = (cfg.trigger_prizes || {})[k];
          const setOwn = (rows) => {
            const tp = { ...(cfg.trigger_prizes || {}) };
            if (rows) tp[k] = rows; else delete tp[k];
            setCfg({ ...cfg, trigger_prizes: tp });
          };
          return (
            <div key={k} className="trigger-row">
              <label className="check">
                <input type="checkbox" checked={!!cfg.triggers[k]} onChange={(e) => setCfg({ ...cfg, triggers: { ...cfg.triggers, [k]: e.target.checked } })} /> {TRIGGER_LABEL[k]}
              </label>
              <label className="check small">
                <input type="checkbox" checked={!!own} disabled={!cfg.triggers[k]} onChange={(e) => setOwn(e.target.checked ? cfg.prizes.map((p) => ({ ...p })) : null)} /> جدول جوائز خاص بهذا المحفّز
              </label>
              {own && (
                <div className="scrollx">
                  <table className="list keep">
                    <thead><tr><th>مفعّلة</th><th>النوع</th><th>القيمة</th><th>الوزن</th><th /></tr></thead>
                    <tbody>
                      {own.map((p, i) => {
                        const upd = (patch) => setOwn(own.map((x, j) => (j === i ? { ...x, ...patch } : x)));
                        return (
                          <tr key={i}>
                            <td><input type="checkbox" checked={p.enabled} onChange={(e) => upd({ enabled: e.target.checked })} /></td>
                            <td><select value={p.type} onChange={(e) => upd({ type: e.target.value })}>{Object.entries(PRIZE_LABEL).map(([t, v]) => <option key={t} value={t}>{v}</option>)}</select></td>
                            <td><input className="mono narrow" type="number" min="0" step="any" value={p.value} onChange={(e) => upd({ value: e.target.value })} /></td>
                            <td><input className="mono narrow" type="number" min="0" step="any" value={p.weight} onChange={(e) => upd({ weight: e.target.value })} /></td>
                            <td><button className="danger-ghost" onClick={() => setOwn(own.filter((_, j) => j !== i))}>حذف</button></td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                  <button onClick={() => setOwn([...own, { type: "discount", value: 10, weight: 1, enabled: true }])}>+ جائزة</button>
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div className="panel">
        <h2>الجوائز والاحتمالات</h2>
        <p className="muted">الوزن نسبي: الاحتمال = وزن الجائزة ÷ مجموع أوزان الجوائز المفعّلة ({totalWeight || 0}).</p>
        <div className="scrollx">
          <table className="list keep">
            <thead>
              <tr><th>مفعّلة</th><th>النوع</th><th>القيمة</th><th>الوزن</th><th>الاحتمال</th><th /></tr>
            </thead>
            <tbody>
              {cfg.prizes.map((p, i) => (
                <tr key={i}>
                  <td><input type="checkbox" checked={p.enabled} onChange={(e) => setPrize(i, { enabled: e.target.checked })} /></td>
                  <td>
                    <select value={p.type} onChange={(e) => setPrize(i, { type: e.target.value })}>
                      {Object.entries(PRIZE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                    </select>
                  </td>
                  <td><input className="mono narrow" type="number" min="0" step="any" value={p.value} onChange={(e) => setPrize(i, { value: e.target.value })} /></td>
                  <td><input className="mono narrow" type="number" min="0" step="any" value={p.weight} onChange={(e) => setPrize(i, { weight: e.target.value })} /></td>
                  <td className="mono">{p.enabled && totalWeight ? `${((Number(p.weight) / totalWeight) * 100).toFixed(2)}%` : "—"}</td>
                  <td><button className="danger-ghost" onClick={() => setCfg({ ...cfg, prizes: cfg.prizes.filter((_, j) => j !== i) })}>حذف</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <button onClick={() => setCfg({ ...cfg, prizes: [...cfg.prizes, { type: "discount", value: 10, weight: 1, enabled: true }] })}>+ إضافة جائزة</button>
      </div>

      <form className="panel" onSubmit={doGrant}>
        <h2>منح بطاقة أو كوبون يدويًا</h2>
        <div className="grid-form">
          <label>Telegram ID<input className="mono" required value={grant.uid} onChange={(e) => setGrant({ ...grant, uid: e.target.value.replace(/\D/g, "") })} /></label>
          <label>النوع
            <select value={grant.type} onChange={(e) => setGrant({ ...grant, type: e.target.value })}>
              <option value="">بطاقة خدش (جائزة عشوائية)</option>
              {Object.entries(PRIZE_LABEL).map(([k, v]) => <option key={k} value={k}>كوبون: {v}</option>)}
            </select>
          </label>
          {grant.type && <label>القيمة<input className="mono" type="number" required min="0" step="any" value={grant.value} onChange={(e) => setGrant({ ...grant, value: e.target.value })} /></label>}
          {grant.type && <label>الصلاحية (ساعات)<input className="mono" type="number" min="1" max="720" value={grant.hours} onChange={(e) => setGrant({ ...grant, hours: e.target.value })} /></label>}
        </div>
        <label className="check"><input type="checkbox" checked={grant.notify} onChange={(e) => setGrant({ ...grant, notify: e.target.checked })} /> إشعار المستخدم عبر تلجرام</label>
        <button className="primary" type="submit">منح</button>
      </form>

      <div className="panel">
        <div className="topbar">
          <h2>البطاقات والكوبونات</h2>
          <input className="narrow-wide" inputMode="numeric" placeholder="تصفية بـ Telegram ID" value={uidFilter} onChange={(e) => setUidFilter(e.target.value.replace(/\D/g, ""))} />
        </div>
        <div className="scrollx">
          <table className="list keep">
            <thead>
              <tr><th>المستخدم</th><th>الحدث</th><th>الجائزة</th><th>الحالة</th><th>تنتهي</th><th /></tr>
            </thead>
            <tbody>
              {(cards?.cards || []).map((c) => (
                <tr key={c.id}>
                  <td className="mono">{c.uid}</td>
                  <td>{c.event}</td>
                  <td>{c.type ? `${PRIZE_LABEL[c.type] || c.type}: ${c.value}` : "—"}</td>
                  <td><span className={`badge ${STATE_BADGE[c.state]}`}>{c.revoked ? "ملغاة" : STATE_LABEL[c.state]}</span></td>
                  <td className="mono">{fmtTime(c.expires_at)}</td>
                  <td className="row-gap">
                    {c.state !== "new" && !c.revoked && c.state !== "used" && (
                      <button onClick={() => act(() => api.extendReward(c.id, 24))}>+24س</button>
                    )}
                    {!c.revoked && c.state !== "used" && (
                      <button className="danger-ghost" onClick={() => act(() => api.revokeReward(c.id))}>إلغاء</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {cards && cards.cards.length === 0 && <div className="empty">لا توجد بطاقات.</div>}
      </div>
    </>
  );
}
