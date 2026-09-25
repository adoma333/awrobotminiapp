import React, { useEffect, useMemo, useState } from "react";
import { api } from "../api";

const TARGET = { all: "كل المستخدمين", filter: "مجموعة بفلتر", user: "مستخدم واحد" };
const FILTER_LABEL = { active: "اشتراك فعّال", expired: "اشتراك منتهٍ", no_sub: "بلا اشتراك قط", unlinked: "غير مربوط", linked: "مربوط", low_balance: "رصيد أقل من", lang: "اللغة", phone_prefix: "رمز الدولة (الهاتف)" };
const when = (ts) => (ts ? new Date(ts * 1000).toLocaleString("ar-u-nu-latn", { dateStyle: "short", timeStyle: "short" }) : "—");
const EMPTY = { target: "all", uid: "", filter: {}, title_ar: "", title_en: "", body_ar: "", body_en: "", via_bot: false };

export default function Notifications({ canWrite }) {
  const [m, setM] = useState(EMPTY);
  const [count, setCount] = useState(null);
  const [hist, setHist] = useState(null);
  const [q, setQ] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const target = useMemo(() => ({ target: m.target, uid: m.target === "user" ? m.uid || null : null, filter: m.target === "filter" ? m.filter : {} }), [m.target, m.uid, m.filter]);
  const loadHist = () => api.broadcasts().then((r) => setHist(r.rows)).catch(() => setHist([]));
  useEffect(() => { loadHist(); }, []);
  useEffect(() => {
    if (m.target === "user" && !/^\d{1,15}$/.test(m.uid)) return setCount(null);
    const id = setTimeout(() => api.notifPreview(target).then((r) => setCount(r.count)).catch(() => setCount(null)), 300);
    return () => clearTimeout(id);
  }, [target]); // eslint-disable-line react-hooks/exhaustive-deps

  const set = (k) => (e) => setM({ ...m, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const setF = (k, v) => setM({ ...m, filter: { ...m.filter, [k]: v } });
  async function send() {
    if (!window.confirm(`إرسال الإشعار إلى ${count ?? "?"} مستخدم${m.via_bot ? " (وعبر البوت أيضًا)" : ""}؟`)) return;
    setBusy(true); setMsg("");
    try {
      const r = await api.broadcast({ ...m, uid: m.target === "user" ? m.uid : null, filter: m.target === "filter" ? m.filter : {} });
      setMsg(`✓ أُرسل إلى ${r.all ? "كل المستخدمين" : `${r.count} مستخدم`}`);
      setM(EMPTY);
      loadHist();
    } catch (e) { setMsg(`✗ ${e.detail || "فشل الإرسال"}`); } finally { setBusy(false); }
  }
  const shown = (hist || []).filter((h) => !q || `${h.title_ar} ${h.title_en} ${h.body_ar} ${h.uid || ""}`.toLowerCase().includes(q.toLowerCase()));

  return (
    <>
      <div className="topbar"><h1>الإشعارات</h1></div>
      <p className="muted" style={{ marginTop: -8 }}>إشعارات النشاط (الدفع، الإيداع والسحب، الصفقات، التنبيهات الأمنية، حالة الحساب والتذاكر) تصل تلقائيًا. من هنا ترسل إشعارًا مخصّصًا يُحفظ في سجل المستخدم (🔔).</p>
      {canWrite && (
        <div className="panel">
          <h2>إشعار جديد</h2>
          <div className="tabs">
            {Object.entries(TARGET).map(([k, v]) => <button key={k} className={`tab ${m.target === k ? "active" : ""}`} onClick={() => setM({ ...m, target: k })}>{v}</button>)}
          </div>
          {m.target === "user" && <input className="mono narrow-wide" placeholder="Telegram ID" value={m.uid} onChange={(e) => setM({ ...m, uid: e.target.value.replace(/\D/g, "") })} />}
          {m.target === "filter" && (
            <div className="filter-grid">
              {["active", "expired", "no_sub", "unlinked", "linked"].map((k) => (
                <label key={k} className="check"><input type="checkbox" checked={!!m.filter[k]} onChange={(e) => setF(k, e.target.checked)} />{FILTER_LABEL[k]}</label>
              ))}
              <label className="inline-field">{FILTER_LABEL.low_balance}<input type="number" min="0" placeholder="مثل 100" value={m.filter.low_balance || ""} onChange={(e) => setF("low_balance", e.target.value ? Number(e.target.value) : "")} /></label>
              <label className="inline-field">{FILTER_LABEL.lang}<select value={m.filter.lang || ""} onChange={(e) => setF("lang", e.target.value)}><option value="">الكل</option><option value="ar">العربية</option><option value="en">English</option></select></label>
              <label className="inline-field">{FILTER_LABEL.phone_prefix}<input className="mono" placeholder="+966" value={m.filter.phone_prefix || ""} onChange={(e) => setF("phone_prefix", e.target.value.replace(/[^\d+]/g, ""))} /></label>
            </div>
          )}
          <div className="grid-form">
            <label>العنوان (عربي)<input value={m.title_ar} maxLength={120} onChange={set("title_ar")} /></label>
            <label>Title (English)<input value={m.title_en} maxLength={120} onChange={set("title_en")} dir="ltr" /></label>
            <label>النص (عربي)<textarea rows={3} value={m.body_ar} maxLength={1000} onChange={set("body_ar")} /></label>
            <label>Body (English)<textarea rows={3} value={m.body_en} maxLength={1000} onChange={set("body_en")} dir="ltr" /></label>
          </div>
          <label className="check"><input type="checkbox" checked={m.via_bot} onChange={set("via_bot")} />إرسال نسخة عبر رسالة البوت في تلجرام أيضًا</label>
          <div className="row-gap">
            <button className="primary" disabled={busy || !(m.title_ar || m.title_en) || (m.target === "user" && !m.uid)} onClick={send}>إرسال</button>
            <span className="muted">المستلمون: <b className="mono">{count ?? "—"}</b></span>
          </div>
          {msg && <p className={msg.startsWith("✗") ? "error-text" : "muted"}>{msg}</p>}
        </div>
      )}
      <div className="panel">
        <div className="topbar"><h2>سجل الإشعارات المرسلة</h2><input className="narrow-wide" placeholder="بحث…" value={q} onChange={(e) => setQ(e.target.value)} /></div>
        {!hist ? <p className="muted">جارٍ التحميل…</p> : shown.length === 0 ? <div className="empty">لا إشعارات بعد.</div> : (
          <div className="audit-list">
            {shown.map((h) => (
              <div key={h.id} className="audit">
                <div className="audit-top"><b>{h.title_ar || h.title_en}</b><span className="badge neutral">{h.all ? "الجميع" : h.target === "user" ? `مستخدم ${h.uid}` : `${h.count} مستخدم`}</span></div>
                {h.body_ar && <span className="muted">{h.body_ar}</span>}
                <div className="audit-meta">
                  <span>{when(h.at)}</span><span>بواسطة <span className="mono">{h.by}</span></span>
                  {Object.keys(h.filter || {}).length > 0 && <span>الفلتر: {Object.entries(h.filter).map(([k, v]) => `${FILTER_LABEL[k] || k}${v === true ? "" : ` ${v}`}`).join("، ")}</span>}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  );
}
