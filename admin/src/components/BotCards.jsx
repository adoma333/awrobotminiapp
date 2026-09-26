import React, { useEffect, useState } from "react";
import { api } from "../api";

const preview = (q) => `/api/admin/cards/preview?${new URLSearchParams(q).toString()}`;

/** بطاقات GIF المتحركة التي تُرفق تلقائيًا برسائل البوت: تشغيل عام، تشغيل لكل نوع، معاينة حيّة. */
export default function BotCards({ canWrite }) {
  const [c, setC] = useState(null);
  const [lang, setLang] = useState("ar");
  const [text, setText] = useState("🎁 هديتك: خصم 15% صالح 48 ساعة");
  const [probe, setProbe] = useState("");
  const [msg, setMsg] = useState("");
  const load = () => api.cards().then(setC).catch(() => setMsg("تعذّر التحميل"));
  useEffect(() => { load(); }, []);
  if (!c) return <p className="muted">{msg || "جارٍ التحميل…"}</p>;
  async function save(patch) {
    setMsg("");
    try { setC({ ...c, ...(await api.saveCards(patch)) }); setMsg("✓ تم الحفظ"); } catch (e) { setMsg(`✗ ${e.detail || "فشل الحفظ"}`); }
  }
  return (
    <>
      <div className="topbar"><h1>بطاقات رسائل البوت (GIF)</h1></div>
      <div className="panel">
        <p className="muted">كل رسالة يرسلها البوت للمستخدم تُرفق معها بطاقة متحركة بتصميم AW تُولَّد تلقائيًا حسب محتوى الرسالة (هدية، عرض، تفعيل اشتراك، دفعة، تذكير، دعم…) مع إبراز القيمة (خصم %، مبلغ، أيام). كل تصميم يُولَّد ويُرفع مرة واحدة ثم يُعاد استخدامه — سريع وبلا ضغط على الخادم. لا تُرفق برسائل الأدمن والقنوات.</p>
        <label className="check"><input type="checkbox" checked={!!c.enabled} onChange={(e) => save({ enabled: e.target.checked })} disabled={!canWrite} />تشغيل البطاقات مع رسائل البوت</label>
        <p className="muted">تصاميم مخزّنة حاليًا: <b className="mono">{c.cached}</b>
          {canWrite && <button className="danger-ghost" style={{ marginInlineStart: 12 }} onClick={async () => { await api.clearCards(); setMsg("✓ تم المسح — ستُولَّد من جديد عند الإرسال"); load(); }}>مسح الذاكرة وإعادة التوليد</button>}
        </p>
        {msg && <p className={msg.startsWith("✗") ? "error-text" : "muted"}>{msg}</p>}
      </div>

      <div className="panel">
        <h2>جرّب رسالة</h2>
        <div className="grid-form">
          <label>نص الرسالة<input value={text} onChange={(e) => setText(e.target.value)} /></label>
          <label>اللغة<select value={lang} onChange={(e) => setLang(e.target.value)}><option value="ar">العربية</option><option value="en">English</option></select></label>
        </div>
        <button className="primary" onClick={() => setProbe(preview({ text, lang, t: Date.now() }))}>معاينة</button>
        {probe && <img className="card-preview" src={probe} alt="" />}
      </div>

      <div className="cards-grid">
        {c.catalog.map((k) => (
          <div key={k.kind} className={`panel card-kind ${c.kinds[k.kind] === false ? "is-off" : ""}`}>
            <img className="card-preview" loading="lazy" src={preview({ kind: k.kind, lang, hl: "" })} alt={k.label} />
            <div className="card-kind-row">
              <b>{lang === "ar" ? k.title_ar : k.title_en}</b>
              <span className="badge neutral mono">{k.label}</span>
            </div>
            <label className="check"><input type="checkbox" checked={c.kinds[k.kind] !== false} disabled={!canWrite || !c.enabled}
              onChange={(e) => save({ kinds: { ...c.kinds, [k.kind]: e.target.checked } })} />مفعّل لهذا النوع</label>
          </div>
        ))}
      </div>
    </>
  );
}
