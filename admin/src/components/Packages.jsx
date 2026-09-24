import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api";

const EMPTY = {
  name_ar: "", name_en: "", price_usd: "", price_stars: "", duration_days: 30, sort_order: 0, active: true, featured: false,
  tagline_ar: "", tagline_en: "", features_ar: "", features_en: "",
};
const lines = (v) => (Array.isArray(v) ? v.join("\n") : v || "");
const numOrNull = (v) => (v === "" || v === null || v === undefined ? null : Number(v));

/** إدارة الباقات: الأسعار بالدولار (NOWPayments) والنجوم وTON، المدة، الترتيب والتفعيل. */
export default function Packages() {
  const [rows, setRows] = useState(null);
  const [edit, setEdit] = useState(null); // { id?, ...fields }
  const [msg, setMsg] = useState("");

  const load = useCallback(() => {
    api.packages().then((r) => setRows(r.packages)).catch(() => setMsg("تعذّر التحميل."));
  }, []);
  useEffect(load, [load]);

  async function save(e) {
    e.preventDefault();
    setMsg("");
    const data = {
      name_ar: edit.name_ar.trim(),
      name_en: edit.name_en.trim(),
      price_usd: Number(edit.price_usd),
      price_stars: numOrNull(edit.price_stars),
      duration_days: Number(edit.duration_days),
      sort_order: Number(edit.sort_order) || 0,
      active: Boolean(edit.active),
      featured: Boolean(edit.featured),
      tagline_ar: edit.tagline_ar || "",
      tagline_en: edit.tagline_en || "",
      features_ar: lines(edit.features_ar),
      features_en: lines(edit.features_en),
    };
    try {
      if (edit.id) await api.updatePackage(edit.id, data);
      else await api.createPackage(data);
      setEdit(null);
      setMsg("✅ تم الحفظ");
      load();
    } catch (err) {
      setMsg(`❌ ${err.detail || "تعذّر الحفظ"}`);
    }
  }

  async function seed() {
    try {
      const r = await api.seedPackages();
      setMsg(r.created.length ? `✅ أُضيفت ${r.created.length} باقات` : "الباقات المقترحة موجودة مسبقًا");
      load();
    } catch {
      setMsg("❌ تعذّر الاستيراد");
    }
  }

  async function remove(p) {
    if (!window.confirm(`حذف الباقة "${p.name_ar}"؟`)) return;
    try { await api.deletePackage(p.id); load(); } catch { setMsg("❌ تعذّر الحذف"); }
  }

  const f = (k) => ({ value: edit[k] ?? "", onChange: (e) => setEdit({ ...edit, [k]: e.target.value }) });

  return (
    <>
      <div className="topbar">
        <h1>الباقات</h1>
        <div className="row-gap">
          {msg && <span className="muted">{msg}</span>}
          <button onClick={seed}>استيراد الباقات المقترحة</button>
          <button className="primary" onClick={() => setEdit({ ...EMPTY })}>+ باقة جديدة</button>
        </div>
      </div>

      {edit && (
        <form className="panel" onSubmit={save}>
          <h2>{edit.id ? "تعديل باقة" : "باقة جديدة"}</h2>
          <div className="grid-form">
            <label>الاسم بالعربية<input required {...f("name_ar")} /></label>
            <label>الاسم بالإنجليزية<input required {...f("name_en")} /></label>
            <label>السعر ($)<input className="mono" type="number" required min="0" step="0.01" {...f("price_usd")} /></label>
            <label>السعر بالنجوم (اختياري)<input className="mono" type="number" min="1" step="1" {...f("price_stars")} /></label>
            <label>المدة (أيام)<input className="mono" type="number" required min="1" {...f("duration_days")} /></label>
            <label>الترتيب<input className="mono" type="number" {...f("sort_order")} /></label>
            <label>وصف قصير بالعربية<input {...f("tagline_ar")} placeholder="مثل: الأكثر طلبًا" /></label>
            <label>وصف قصير بالإنجليزية<input {...f("tagline_en")} placeholder="e.g. Most popular" /></label>
          </div>
          <div className="grid-form">
            <label>المزايا بالعربية (سطر لكل ميزة)<textarea rows={5} value={lines(edit.features_ar)} onChange={(e) => setEdit({ ...edit, features_ar: e.target.value })} /></label>
            <label>المزايا بالإنجليزية (سطر لكل ميزة)<textarea rows={5} value={lines(edit.features_en)} onChange={(e) => setEdit({ ...edit, features_en: e.target.value })} /></label>
          </div>
          <p className="muted">سعر TON يُحسب تلقائيًا من السعر بالدولار حسب سعر TON الحالي في السوق.</p>
          <label className="check"><input type="checkbox" checked={edit.active} onChange={(e) => setEdit({ ...edit, active: e.target.checked })} /> ظاهرة للمستخدمين</label>
          <label className="check"><input type="checkbox" checked={edit.featured} onChange={(e) => setEdit({ ...edit, featured: e.target.checked })} /> مميّزة (شارة "الأكثر طلبًا")</label>
          <div className="row-gap">
            <button className="primary" type="submit">حفظ</button>
            <button type="button" onClick={() => setEdit(null)}>إلغاء</button>
          </div>
        </form>
      )}

      {rows && rows.length === 0 && <div className="empty">لا توجد باقات بعد.</div>}
      {rows && rows.length > 0 && (
        <div className="scrollx">
          <table className="list keep">
            <thead>
              <tr><th>الباقة</th><th>$</th><th>⭐</th><th>المزايا</th><th>المدة</th><th>الحالة</th><th /></tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.id}>
                  <td>{p.name_ar} · <span className="muted">{p.name_en}</span></td>
                  <td className="mono">{p.price_usd}</td>
                  <td className="mono">{p.price_stars ?? "—"}</td>
                  <td className="mono">{(p.features_ar || []).length}</td>
                  <td className="mono">{p.duration_days}</td>
                  <td>
                    <span className={`badge ${p.active === false ? "neutral" : "approved"}`}>{p.active === false ? "مخفية" : "ظاهرة"}</span>
                    {p.featured && <span className="badge pending" style={{ marginInlineStart: 6 }}>مميّزة</span>}
                  </td>
                  <td className="row-gap">
                    <button onClick={() => setEdit({ ...EMPTY, ...p })}>تعديل</button>
                    <button className="danger-ghost" onClick={() => remove(p)}>حذف</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
