import React, { useEffect, useState } from "react";
import { api } from "../api";

const FREQ = { once: "مرة واحدة فقط", every_open: "عند كل دخول", daily: "مرة في اليوم", every_x_days: "كل X يوم" };
const AUD = { all: "كل المستخدمين", active: "الاشتراك فعّال", expired: "الاشتراك منتهٍ", no_sub: "بلا اشتراك", unlinked: "غير مربوطين", linked: "مربوطون" };
const CTA = { close: "إغلاق النافذة", plans: "فتح الباقات", support: "فتح الدعم", url: "رابط خارجي" };
const ICON_LABEL = { bolt: "⚡ تنفيذ", chart: "📈 أداء", shield: "🛡 أمان", cloud: "☁ سحابة", headset: "🎧 دعم", bell: "🔔 إشعارات", trophy: "🏆 ترتيب", gift: "🎁 مكافأة", star: "⭐ نجمة", wallet: "👛 محفظة", globe: "🌐 لغات", check: "✓ عام" };
const toLocal = (ts) => (ts ? new Date(ts * 1000 - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16) : "");
const fromLocal = (v) => (v ? Math.floor(new Date(v).getTime() / 1000) : 0);

async function fileToB64(file) {
  return new Promise((res, rej) => {
    const fr = new FileReader();
    fr.onload = () => res(fr.result);
    fr.onerror = rej;
    fr.readAsDataURL(file);
  });
}

export default function Announcements({ canWrite }) {
  const [list, setList] = useState(null);
  const [icons, setIcons] = useState([]);
  const [edit, setEdit] = useState(null);
  const [msg, setMsg] = useState("");
  const load = () => api.announcements().then((r) => { setList(r.items); setIcons(r.icons); return r; });
  useEffect(() => { load(); }, []);

  async function save(reset = false) {
    setMsg("");
    try {
      const { id, views, dismissals, updated_at, updated_by, ...patch } = edit; // eslint-disable-line no-unused-vars
      const r = id ? await api.saveAnnouncement(id, { ...patch, reset_views: reset }) : await api.createAnnouncement(patch);
      setEdit(r);
      await load();
      setMsg(reset ? "✓ حُفظت وستظهر من جديد لكل المستخدمين" : "✓ تم الحفظ");
    } catch (e) { setMsg(`✗ ${e.detail || "فشل الحفظ"}`); }
  }
  async function toggle(a) {
    await api.saveAnnouncement(a.id, { enabled: !a.enabled });
    load();
  }

  if (!list) return <p className="muted">جارٍ التحميل…</p>;
  return (
    <>
      <div className="topbar">
        <h1>نافذة التحديثات (ما الجديد)</h1>
        {canWrite && (
          <div className="row-gap">
            <button onClick={async () => { await api.seedAnnouncement(); load(); }}>استعادة نافذة الإطلاق الافتراضية</button>
            <button className="primary" onClick={() => setEdit({ enabled: false, priority: 5, frequency: "once", every_days: 3, audience: "all", allow_dismiss: true, features: [], cta_action: "close", title_ar: "", title_en: "" })}>نافذة جديدة</button>
          </div>
        )}
      </div>
      <p className="muted" style={{ marginTop: -8 }}>تظهر للمستخدم عند الدخول أول نافذة مفعّلة (الأعلى أولوية) يحين وقتها حسب التكرار والجمهور والتاريخ.</p>
      {list.length === 0 ? <div className="empty">لا توجد نوافذ. استعد الافتراضية أو أنشئ نافذة جديدة.</div> : (
        <div className="audit-list">
          {list.map((a) => (
            <div key={a.id} className="audit">
              <div className="audit-top">
                <b>{a.title_ar || a.title_en}</b>
                <div className="row-gap">
                  <span className={`badge ${a.enabled ? "approved" : "neutral"}`}>{a.enabled ? "مفعّلة" : "موقوفة"}</span>
                  {canWrite && <button onClick={() => toggle(a)}>{a.enabled ? "إيقاف" : "تشغيل"}</button>}
                  <button onClick={() => setEdit(a)}>{canWrite ? "تعديل" : "عرض"}</button>
                  {canWrite && <button className="danger-ghost" onClick={async () => { if (window.confirm("حذف النافذة نهائيًا؟")) { await api.deleteAnnouncement(a.id); load(); } }}>حذف</button>}
                </div>
              </div>
              <div className="audit-meta">
                <span>التكرار: {FREQ[a.frequency]}{a.frequency === "every_x_days" ? ` (${a.every_days})` : ""}</span>
                <span>الجمهور: {AUD[a.audience]}</span>
                <span>الأولوية: {a.priority}</span>
                <span>المشاهدات: {a.views || 0}</span>
                <span>"لا تظهر مرة أخرى": {a.dismissals || 0}</span>
                {a.starts_at ? <span>من {new Date(a.starts_at * 1000).toLocaleDateString("ar-u-nu-latn")}</span> : null}
                {a.ends_at ? <span>حتى {new Date(a.ends_at * 1000).toLocaleDateString("ar-u-nu-latn")}</span> : null}
              </div>
            </div>
          ))}
        </div>
      )}
      {edit && <Editor a={edit} setA={setEdit} icons={icons} canWrite={canWrite} onSave={save} msg={msg} onClose={() => { setEdit(null); setMsg(""); }} />}
    </>
  );
}

function Editor({ a, setA, icons, canWrite, onSave, msg, onClose }) {
  const [uploading, setUploading] = useState(false);
  const set = (k) => (e) => setA({ ...a, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.type === "number" ? Number(e.target.value) : e.target.value });
  const setFeat = (i, k, v) => setA({ ...a, features: a.features.map((f, j) => (j === i ? { ...f, [k]: v } : f)) });
  async function upload(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!/^image\/(jpeg|png|webp)$/.test(file.type) || file.size > 1_500_000) return alert("JPG/PNG/WebP حتى 1.5MB");
    setUploading(true);
    try { setA({ ...a, image: (await api.uploadImage(await fileToB64(file))).url }); } finally { setUploading(false); }
  }
  const T = (k, label, long) => (
    <label>{label}{long ? <textarea rows={3} value={a[k] || ""} onChange={set(k)} disabled={!canWrite} dir={k.endsWith("_en") ? "ltr" : "rtl"} /> : <input value={a[k] || ""} onChange={set(k)} disabled={!canWrite} dir={k.endsWith("_en") ? "ltr" : "rtl"} />}</label>
  );
  return (
    <>
      <div className="overlay" onClick={onClose} />
      <aside className="sheet wide">
        <div className="sheet-head"><h2>{a.id ? "تعديل النافذة" : "نافذة جديدة"}</h2><button onClick={onClose}>إغلاق</button></div>
        <label className="check"><input type="checkbox" checked={!!a.enabled} onChange={set("enabled")} disabled={!canWrite} />مفعّلة (تظهر للمستخدمين)</label>
        <h3>الظهور</h3>
        <div className="grid-form">
          <label>التكرار<select value={a.frequency} onChange={set("frequency")} disabled={!canWrite}>{Object.entries(FREQ).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
          {a.frequency === "every_x_days" && <label>كل (يوم)<input type="number" min="1" max="90" value={a.every_days} onChange={set("every_days")} disabled={!canWrite} /></label>}
          <label>فئة المستخدمين<select value={a.audience} onChange={set("audience")} disabled={!canWrite}>{Object.entries(AUD).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
          <label>الأولوية (0-100)<input type="number" min="0" max="100" value={a.priority} onChange={set("priority")} disabled={!canWrite} /></label>
          <label>بداية العرض<input type="datetime-local" value={toLocal(a.starts_at)} onChange={(e) => setA({ ...a, starts_at: fromLocal(e.target.value) })} disabled={!canWrite} /></label>
          <label>نهاية العرض<input type="datetime-local" value={toLocal(a.ends_at)} onChange={(e) => setA({ ...a, ends_at: fromLocal(e.target.value) })} disabled={!canWrite} /></label>
        </div>
        <label className="check"><input type="checkbox" checked={!!a.allow_dismiss} onChange={set("allow_dismiss")} disabled={!canWrite} />إظهار خيار "لا تظهر مرة أخرى"</label>
        <h3>المحتوى</h3>
        <div className="grid-form">
          {T("badge_ar", "الشارة")}{T("badge_en", "Badge")}
          {T("title_ar", "العنوان")}{T("title_en", "Title")}
          {T("subtitle_ar", "الوصف المختصر", true)}{T("subtitle_en", "Subtitle", true)}
          {T("body_ar", "نص إضافي", true)}{T("body_en", "Extra body", true)}
          {T("footnote_ar", "حاشية (مثل تنبيه المخاطر)")}{T("footnote_en", "Footnote")}
        </div>
        <h3>الصورة (اختياري)</h3>
        <div className="row-gap">
          {a.image && <img src={a.image} alt="" className="ann-thumb" />}
          {canWrite && <label className="file-btn">{uploading ? "جارٍ الرفع…" : "رفع صورة JPG/PNG/WebP"}<input type="file" accept="image/jpeg,image/png,image/webp" hidden onChange={upload} /></label>}
          {a.image && canWrite && <button className="danger-ghost" onClick={() => setA({ ...a, image: "" })}>إزالة</button>}
        </div>
        <h3>نقاط المزايا</h3>
        {(a.features || []).map((f, i) => (
          <div key={i} className="feat-row">
            <select value={f.icon} onChange={(e) => setFeat(i, "icon", e.target.value)} disabled={!canWrite}>{icons.map((ic) => <option key={ic} value={ic}>{ICON_LABEL[ic] || ic}</option>)}</select>
            <input placeholder="العنوان" value={f.title_ar} onChange={(e) => setFeat(i, "title_ar", e.target.value)} disabled={!canWrite} />
            <input placeholder="Title" dir="ltr" value={f.title_en} onChange={(e) => setFeat(i, "title_en", e.target.value)} disabled={!canWrite} />
            <textarea rows={2} placeholder="الشرح" value={f.text_ar} onChange={(e) => setFeat(i, "text_ar", e.target.value)} disabled={!canWrite} />
            <textarea rows={2} placeholder="Text" dir="ltr" value={f.text_en} onChange={(e) => setFeat(i, "text_en", e.target.value)} disabled={!canWrite} />
            {canWrite && <button className="danger-ghost" onClick={() => setA({ ...a, features: a.features.filter((_, j) => j !== i) })}>حذف</button>}
          </div>
        ))}
        {canWrite && (a.features || []).length < 8 && <div><button onClick={() => setA({ ...a, features: [...(a.features || []), { icon: "check", title_ar: "", title_en: "", text_ar: "", text_en: "" }] })}>+ نقطة</button></div>}
        <h3>زر الإجراء (CTA)</h3>
        <div className="grid-form">
          {T("cta_label_ar", "نص الزر")}{T("cta_label_en", "Button label")}
          <label>عند الضغط<select value={a.cta_action} onChange={set("cta_action")} disabled={!canWrite}>{Object.entries(CTA).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
          {a.cta_action === "url" && <label>الرابط<input dir="ltr" placeholder="https://" value={a.cta_url || ""} onChange={set("cta_url")} disabled={!canWrite} /></label>}
        </div>
        {canWrite && (
          <div className="row-gap sticky-actions">
            <button className="primary" onClick={() => onSave(false)}>حفظ</button>
            {a.id && <button onClick={() => onSave(true)}>حفظ وإعادة العرض للجميع</button>}
          </div>
        )}
        {msg && <p className={msg.startsWith("✗") ? "error-text" : "muted"}>{msg}</p>}
      </aside>
    </>
  );
}
