import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api";

const EMPTY = { name_ar: "", name_en: "", price_usd: "", price_stars: "", price_ton: "", duration_days: 30, sort_order: 0, active: true };
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
      price_ton: numOrNull(edit.price_ton),
      duration_days: Number(edit.duration_days),
      sort_order: Number(edit.sort_order) || 0,
      active: Boolean(edit.active),
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
            <label>السعر بـ TON (اختياري)<input className="mono" type="number" min="0" step="0.01" {...f("price_ton")} /></label>
            <label>المدة (أيام)<input className="mono" type="number" required min="1" {...f("duration_days")} /></label>
            <label>الترتيب<input className="mono" type="number" {...f("sort_order")} /></label>
          </div>
          <label className="check"><input type="checkbox" checked={edit.active} onChange={(e) => setEdit({ ...edit, active: e.target.checked })} /> ظاهرة للمستخدمين</label>
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
              <tr><th>الباقة</th><th>$</th><th>⭐</th><th>TON</th><th>المدة</th><th>الحالة</th><th /></tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.id}>
                  <td>{p.name_ar} · <span className="muted">{p.name_en}</span></td>
                  <td className="mono">{p.price_usd}</td>
                  <td className="mono">{p.price_stars ?? "—"}</td>
                  <td className="mono">{p.price_ton ?? "—"}</td>
                  <td className="mono">{p.duration_days}</td>
                  <td><span className={`badge ${p.active === false ? "neutral" : "approved"}`}>{p.active === false ? "مخفية" : "ظاهرة"}</span></td>
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
