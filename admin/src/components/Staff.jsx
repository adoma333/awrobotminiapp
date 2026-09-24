import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api";

const AREA = { ceo: "الإحصاءات", users: "المستخدمون", rewards: "المكافآت", packages: "الباقات", settings: "مركز التحكم", system: "النظام", staff: "الفريق", audit: "سجل العمليات" };
const ROLE_LABEL = { owner: "مالك", manager: "مدير", support: "دعم فني", viewer: "مشاهد" };

/** فريق العمل: إضافة موظفين بدور محدد (يدخلون بأمر /admin في البوت). */
export default function Staff() {
  const [d, setD] = useState(null);
  const [form, setForm] = useState({ id: "", name: "", role: "support" });
  const [msg, setMsg] = useState("");
  const load = useCallback(() => api.staff().then(setD).catch(() => setMsg("تعذّر التحميل.")), []);
  useEffect(() => { load(); }, [load]);

  async function add(e) {
    e.preventDefault();
    try {
      await api.saveStaff({ ...form, id: form.id.trim() });
      setForm({ id: "", name: "", role: "support" });
      setMsg("✅ أُضيف العضو — يدخل بإرسال /admin للبوت");
      load();
    } catch (err) {
      setMsg(`❌ ${err.detail === "owner_is_fixed" ? "هذا الحساب مالك بالفعل" : "تعذّر الحفظ"}`);
    }
  }

  if (!d) return <p className="muted">{msg || "...جارٍ التحميل"}</p>;
  return (
    <>
      <div className="topbar"><h1>فريق العمل</h1>{msg && <span className="muted">{msg}</span>}</div>

      <form className="panel" onSubmit={add}>
        <h2>إضافة عضو</h2>
        <div className="grid-form">
          <label>Telegram ID<input className="mono" required value={form.id} onChange={(e) => setForm({ ...form, id: e.target.value.replace(/\D/g, "") })} /></label>
          <label>الاسم<input value={form.name} maxLength={40} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
          <label>الدور
            <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
              {Object.entries(d.roles).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
        </div>
        <button className="primary" type="submit">إضافة</button>
      </form>

      <div className="panel">
        <h2>الأعضاء</h2>
        <div className="member-list">
          {d.members.map((m) => (
            <div key={m.id} className="member">
              <div>
                <b>{m.name || (m.fixed ? "المالك" : "—")}</b>
                <span className="mono muted">{m.id}</span>
              </div>
              {m.fixed ? (
                <span className="badge approved">{ROLE_LABEL.owner}</span>
              ) : (
                <div className="row-gap">
                  <select value={m.role} onChange={(e) => api.saveStaff({ id: m.id, name: m.name || "", role: e.target.value }).then(load)}>
                    {Object.entries(d.roles).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                  <button className="danger-ghost" onClick={() => api.removeStaff(m.id).then(load)}>إزالة</button>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="panel">
        <h2>صلاحيات كل دور</h2>
        <div className="scrollx">
          <table className="list keep">
            <thead><tr><th>القسم</th>{Object.keys(d.perms).map((r) => <th key={r}>{ROLE_LABEL[r]}</th>)}</tr></thead>
            <tbody>
              {Object.keys(AREA).map((a) => (
                <tr key={a}>
                  <td>{AREA[a]}</td>
                  {Object.keys(d.perms).map((r) => {
                    const p = d.perms[r][a];
                    return <td key={r}>{p === "rw" ? "✏️ تعديل" : p === "r" ? "👁 عرض" : "—"}</td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
