import React, { useEffect, useState } from "react";
import { api } from "../api";

const FREQ = { once: "مرة واحدة فقط", every_open: "عند كل دخول", daily: "مرة في اليوم", every_x_days: "كل X يوم" };
const AUD = { all: "كل المستخدمين", active: "الاشتراك فعّال", expired: "الاشتراك منتهٍ", no_sub: "بلا اشتراك", unlinked: "غير مربوطين", linked: "مربوطون" };
const CTA = { close: "إغلاق النافذة", plans: "فتح الباقات", support: "فتح الدعم", url: "رابط خارجي" };
const ICON_LABEL = { bolt: "⚡ تنفيذ", chart: "📈 أداء", shield: "🛡 أمان", cloud: "☁ سحابة", headset: "🎧 دعم", bell: "🔔 إشعارات", trophy: "🏆 ترتيب", gift: "🎁 مكافأة", star: "⭐ نجمة", wallet: "👛 محفظة", globe: "🌐 لغات", check: "✓ عام" };
const DEFAULT_STYLE = { accent: "#ff8a00", accent2: "#ff5a00", bg: "#0e0b09", text: "#f5efe8", width: 460, position: "bottom", radius: 26, blur: 4,
  theme: "custom", image_mode: "top", image_fit: "cover", image_height: 180, image_radius: 18, image_focus: "center", overlay: 55,
  cta_place: "inline", cta_width: "full", align: "center", title_size: 24, animation: "slide", show_close: true };
const APP_THEME = { dark: { bg: "#151210", text: "#f5efe8" }, light: { bg: "#ffffff", text: "#1b1612" } };
const DEVICES = { phone_s: ["هاتف صغير", 360, 640], phone: ["هاتف", 390, 780], phone_l: ["هاتف كبير", 430, 860], tablet: ["تابلت", 768, 900] };
const EMOJI = { bolt: "⚡", chart: "📈", shield: "🛡", cloud: "☁", headset: "🎧", bell: "🔔", trophy: "🏆", gift: "🎁", star: "⭐", wallet: "👛", globe: "🌐", check: "✓" };
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
      <aside className="sheet wide ann-editor">
        <div className="sheet-head"><h2>{a.id ? "تعديل النافذة" : "نافذة جديدة"}</h2><button onClick={onClose}>إغلاق</button></div>
        <div className="ann-split">
        <div className="ann-form">
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
        </div>
        <Preview a={a} setStyle={(patch) => setA({ ...a, style: { ...DEFAULT_STYLE, ...(a.style || {}), ...patch } })} canWrite={canWrite} />
        </div>
      </aside>
    </>
  );
}

// ───────────── المعاينة الحية + التحكم الكامل بالشكل ─────────────
function Preview({ a, setStyle, canWrite }) {
  const [lang, setLang] = useState("ar");
  const [device, setDevice] = useState("phone");
  const st = { ...DEFAULT_STYLE, ...(a.style || {}) };
  const [, dw, dh] = DEVICES[device];
  const L = (k) => a[`${k}_${lang}`] || a[`${k}_${lang === "ar" ? "en" : "ar"}`] || "";
  const C = (k, label) => (
    <label className="color-field">{label}
      <span><input type="color" value={st[k]} onChange={(e) => setStyle({ [k]: e.target.value })} disabled={!canWrite} /><code>{st[k]}</code></span>
    </label>
  );
  const R = (k, label, min, max) => (
    <label>{label} <b className="mono">{st[k]}</b>
      <input type="range" min={min} max={max} value={st[k]} onChange={(e) => setStyle({ [k]: Number(e.target.value) })} disabled={!canWrite} />
    </label>
  );
  const [appMode, setAppMode] = useState("dark");
  const center = st.position === "center";
  const full = st.position === "fullscreen";
  const app = st.theme === "app";
  const bg = app ? APP_THEME[appMode].bg : st.bg;
  const fg = app ? APP_THEME[appMode].text : st.text;
  const accent = app ? "#ff8a00" : st.accent;
  const accent2 = app ? "#ff5a00" : st.accent2;
  const imgMode = a.image ? st.image_mode : "none";
  const S = (k, label, opts) => (
    <label>{label}
      <select value={st[k]} onChange={(e) => setStyle({ [k]: e.target.value })} disabled={!canWrite}>
        {opts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </label>
  );
  const scale = 0.72; // المعاينة تصغّر المقاسات الحقيقية لتتسع للإطار
  return (
    <div className="ann-preview">
      <div className="row-gap">
        <div className="tabs">
          {Object.entries(DEVICES).map(([k, [l]]) => <button key={k} className={`tab ${device === k ? "active" : ""}`} onClick={() => setDevice(k)}>{l}</button>)}
        </div>
        <div className="tabs">
          <button className={`tab ${lang === "ar" ? "active" : ""}`} onClick={() => setLang("ar")}>ع</button>
          <button className={`tab ${lang === "en" ? "active" : ""}`} onClick={() => setLang("en")}>EN</button>
        </div>
      </div>
      <p className="muted">اسحب الزاوية السفلية للإطار لتغيير حجم الشاشة. المعاينة تتحدث فورًا مع كل تعديل.</p>
      <div className="ann-device" style={{ width: dw, height: Math.min(dh, 720) }}>
        <div className="ann-screen" dir={lang === "ar" ? "rtl" : "ltr"}>
          <div className="ann-app-mock"><span /><span /><span /><span /></div>
          <div className="ann-backdrop" style={{ alignItems: full ? "stretch" : center ? "center" : "flex-end", padding: center ? 12 : 0, backdropFilter: `blur(${st.blur}px)`, WebkitBackdropFilter: `blur(${st.blur}px)` }}>
            <div className={`ann-sheet anim-${st.animation} ${st.align === "start" ? "is-start" : ""} ${full ? "is-full" : ""}`} key={`${st.animation}-${st.position}`} style={{
              maxWidth: full ? "none" : st.width, color: imgMode === "background" && !app ? st.text || "#fff" : fg, borderColor: `${accent}38`,
              borderRadius: full ? 0 : center ? st.radius : `${st.radius}px ${st.radius}px 0 0`,
              background: imgMode === "background"
                ? `linear-gradient(rgba(0,0,0,${st.overlay / 100}), rgba(0,0,0,${Math.min(0.95, st.overlay / 100 + 0.2)})), url("${a.image}") ${st.image_focus} / cover`
                : `radial-gradient(120% 60% at 50% 0%, ${accent}29, transparent 60%), ${bg}`,
            }}>
              {st.show_close && <span className="ann-x">✕</span>}
              {imgMode === "top" || imgMode === "full" ? (
                <img className={`ann-hero-img ${imgMode === "full" ? "is-bleed" : ""}`} src={a.image} alt=""
                  style={{ height: st.image_height * scale, maxHeight: "none", objectFit: st.image_fit, objectPosition: `center ${st.image_focus}`, borderRadius: imgMode === "full" ? 0 : st.image_radius * scale }} />
              ) : imgMode === "none" ? (
                <div className="ann-hero" style={{ background: `linear-gradient(135deg, ${accent}, ${accent2})`, boxShadow: `0 12px 40px ${accent}59` }}>⚡</div>
              ) : null}
              {L("badge") && <span className="ann-badge" style={{ color: accent, borderColor: `${accent}47` }}>{L("badge")}</span>}
              <h2 style={{ fontSize: st.title_size * scale }}>{L("title") || (lang === "ar" ? "عنوان النافذة" : "Window title")}</h2>
              {L("subtitle") && <p className="ann-sub">{L("subtitle")}</p>}
              {(a.features || []).length > 0 && (
                <ul className="ann-feats">
                  {a.features.map((f, i) => (
                    <li key={i}>
                      <span className="ann-ic" style={{ color: accent, background: `${accent}1f` }}>{EMOJI[f.icon] || "✓"}</span>
                      <div><b>{f[`title_${lang}`] || f.title_en || f.title_ar}</b>{(f[`text_${lang}`] || f.text_en) && <p>{f[`text_${lang}`] || f.text_en}</p>}</div>
                    </li>
                  ))}
                </ul>
              )}
              {L("body") && <p className="ann-body">{L("body")}</p>}
              <div className={`ann-cta-wrap ${st.cta_place === "sticky" ? "is-sticky" : ""}`} style={st.cta_place === "sticky" ? { background: `linear-gradient(transparent, ${imgMode === "background" ? "rgba(0,0,0,.85)" : bg} 35%)` } : undefined}>
                <div className="ann-cta" style={{ background: `linear-gradient(135deg, ${accent}, ${accent2})`, width: st.cta_width === "auto" ? "auto" : "100%", padding: st.cta_width === "auto" ? "10px 26px" : undefined }}>{L("cta_label") || (lang === "ar" ? "إغلاق" : "Close")}</div>
              </div>
              {a.allow_dismiss && <div className="ann-never">☐ {lang === "ar" ? "لا تظهر مرة أخرى" : "Don't show again"}</div>}
              {L("footnote") && <p className="ann-foot">{L("footnote")}</p>}
            </div>
          </div>
        </div>
      </div>
      {app && (
        <div className="tabs">
          <button className={`tab ${appMode === "dark" ? "active" : ""}`} onClick={() => setAppMode("dark")}>معاينة ليلي</button>
          <button className={`tab ${appMode === "light" ? "active" : ""}`} onClick={() => setAppMode("light")}>معاينة نهاري</button>
        </div>
      )}
      <h3>المظهر</h3>
      <div className="grid-form">
        {S("theme", "الألوان", [["custom", "ألوان مخصصة (أدناه)"], ["app", "مثل التطبيق — ليلي/نهاري تلقائيًا"]])}
        {S("position", "طريقة الظهور", [["bottom", "من الأسفل (Bottom sheet)"], ["center", "في المنتصف (Modal)"], ["fullscreen", "ملء الشاشة بالكامل"]])}
        {S("animation", "حركة الظهور", [["slide", "انزلاق"], ["fade", "تلاشي"], ["zoom", "تكبير"]])}
        {S("align", "محاذاة النص", [["center", "في المنتصف"], ["start", "من البداية"]])}
      </div>
      {!app && (
        <div className="grid-form">
          {C("accent", "اللون الرئيسي")}{C("accent2", "اللون الثانوي (التدرج)")}{C("bg", "الخلفية")}{C("text", "النص")}
        </div>
      )}
      <h3>الصورة {a.image ? "" : <small className="muted">(ارفع صورة من الحقول لتفعيل خياراتها)</small>}</h3>
      <div className="grid-form">
        {S("image_mode", "مكان الصورة", [["top", "أعلى النافذة"], ["full", "بعرض النافذة كاملًا"], ["background", "خلفية النافذة"]])}
        {S("image_fit", "ملاءمة الصورة", [["cover", "ملء (قص تلقائي)"], ["contain", "كاملة بلا قص"]])}
        {S("image_focus", "نقطة التركيز", [["top", "الأعلى"], ["center", "المنتصف"], ["bottom", "الأسفل"]])}
        {R("image_height", "ارتفاع الصورة (px)", 80, 420)}
        {R("image_radius", "استدارة الصورة", 0, 40)}
        {R("overlay", "تعتيم فوق صورة الخلفية %", 0, 90)}
      </div>
      <h3>الزر والنص</h3>
      <div className="grid-form">
        {S("cta_place", "مكان الزر", [["inline", "بعد المحتوى"], ["sticky", "مثبّت أسفل النافذة دائمًا"]])}
        {S("cta_width", "عرض الزر", [["full", "بعرض كامل"], ["auto", "على قدر النص"]])}
        {R("title_size", "حجم العنوان", 16, 40)}
        <label className="check"><input type="checkbox" checked={st.show_close !== false} onChange={(e) => setStyle({ show_close: e.target.checked })} disabled={!canWrite} />إظهار زر الإغلاق ✕</label>
      </div>
      <div className="grid-form">
        {R("width", "أقصى عرض (px)", 300, 760)}
        {R("radius", "استدارة الزوايا", 0, 40)}
        {R("blur", "تمويه الخلفية", 0, 12)}
      </div>
      {canWrite && <div><button onClick={() => setStyle({ ...DEFAULT_STYLE })}>استعادة الشكل الافتراضي</button></div>}
    </div>
  );
}
