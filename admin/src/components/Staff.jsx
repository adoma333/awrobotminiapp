import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api";

const ROLE_LABEL = { owner: "مالك", manager: "مدير", support: "دعم فني", viewer: "مشاهد" };
// ترتيب الأقسام كما في القائمة الجانبية
const AREA_GROUPS = [
  ["نظرة عامة", ["ceo", "analytics", "system"]],
  ["المستخدمون والمالية", ["users", "packages", "rewards", "gateway", "ton"]],
  ["الدعم والتواصل", ["support", "notifications", "announcements", "cards"]],
  ["النمو والإعدادات", ["growth", "leaderboard", "design", "control", "servers", "export"]],
  ["الإدارة", ["staff", "audit"]],
];
const LEVELS = [["", "مخفي"], ["r", "عرض"], ["rw", "تعديل"]];
const LANGS = { ar: "العربية", en: "English" };
const EMPTY_AGENT = { enabled: false, available: true, skills: [], langs: [], max_active: 0, order: 0 };

/** فريق العمل: كل عضو بصلاحيات مفصّلة لكل صفحة، وما يراه داخلها، وإعدادات استلام تذاكر الدعم. */
export default function Staff({ me }) {
  const [d, setD] = useState(null);
  const [agents, setAgents] = useState(null);
  const [form, setForm] = useState({ id: "", name: "", role: "support" });
  const [edit, setEdit] = useState(null);
  const [msg, setMsg] = useState("");
  const load = useCallback(() => {
    api.staff().then(setD).catch(() => setMsg("تعذّر التحميل."));
    if (me?.perms?.support) api.supportAgents().then(setAgents).catch(() => setAgents(null));
  }, [me]);
  useEffect(() => { load(); }, [load]);

  async function add(e) {
    e.preventDefault();
    try {
      await api.saveStaff({ ...form, id: form.id.trim() });
      setForm({ id: "", name: "", role: "support" });
      setMsg("✅ أُضيف العضو — يدخل بإرسال /admin للبوت. اضغط «تخصيص» لضبط صلاحياته بدقة.");
      load();
    } catch (err) {
      setMsg(`❌ ${err.detail === "owner_is_fixed" ? "هذا الحساب مالك بالفعل" : err.detail === "owner_only" ? "إدارة الفريق للمالك فقط" : "تعذّر الحفظ"}`);
    }
  }

  if (!d) return <p className="muted">{msg || "...جارٍ التحميل"}</p>;
  const canEdit = d.can_edit;
  const agentRows = agents?.rows || [];
  return (
    <>
      <div className="topbar"><h1>فريق العمل والصلاحيات</h1>{msg && <span className="muted">{msg}</span>}</div>
      {!canEdit && <div className="note-box">العرض فقط — إضافة الأعضاء وتعديل صلاحياتهم للمالك وحده.</div>}

      {canEdit && (
        <form className="panel" onSubmit={add}>
          <h2>إضافة عضو</h2>
          <div className="grid-form">
            <label>Telegram ID<input className="mono" inputMode="numeric" required value={form.id} onChange={(e) => setForm({ ...form, id: e.target.value.replace(/\D/g, "") })} /></label>
            <label>الاسم<input value={form.name} maxLength={40} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
            <label>الدور (نقطة بداية للصلاحيات)
              <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                {Object.entries(d.roles).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </label>
          </div>
          <div><button className="primary" type="submit">إضافة</button></div>
        </form>
      )}

      {agentRows.length > 0 && (
        <div className="panel">
          <div className="topbar">
            <h2>موظفو الدعم — التوزيع الحالي</h2>
            <span className="muted">الوضع: {agents.mode === "least_load" ? "الأقل ضغطًا" : agents.mode === "off" ? "بلا توزيع" : "بالترتيب (دوري)"}</span>
          </div>
          <div className="agent-grid">
            {agentRows.map((a) => (
              <div key={a.id} className={`agent-card ${a.available ? "" : "is-off"} ${agents.next === a.id ? "is-next" : ""}`}>
                <div className="agent-top">
                  <b>{a.name}</b>
                  <span className={`badge ${a.available ? "approved" : "neutral"}`}>{a.available ? "متاح" : "غير متاح"}</span>
                  {agents.next === a.id && <span className="badge pending">التالي في الدور</span>}
                </div>
                <div className="agent-stats">
                  <div><span>مفتوحة الآن</span><b className="mono">{a.active}{a.max_active ? `/${a.max_active}` : ""}</b></div>
                  <div><span>أُسندت له</span><b className="mono">{a.assigned_total}</b></div>
                  <div><span>محلولة</span><b className="mono">{a.resolved}</b></div>
                  <div><span>التقييم</span><b className="mono">{a.csat_avg ? `${a.csat_avg}★` : "—"}</b></div>
                </div>
                {(a.skills?.length > 0 || a.langs?.length > 0) && (
                  <div className="chips">
                    {a.skills.map((s) => <span key={s} className="chip">{agents.skills?.[s] || s}</span>)}
                    {a.langs.map((l) => <span key={l} className="chip">{LANGS[l]}</span>)}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="panel">
        <h2>الأعضاء</h2>
        <div className="member-list">
          {d.members.map((m) => (
            <div key={m.id} className="member">
              <div>
                <b>{m.name || (m.fixed ? "المالك" : "—")}</b>
                <span className="mono muted">{m.id}</span>
                <div className="chips">
                  <span className={`badge ${m.fixed ? "approved" : "neutral"}`}>{ROLE_LABEL[m.role] || m.role}{m.custom_perms ? " · مخصّص" : ""}</span>
                  {m.agent?.enabled && <span className={`badge ${m.agent.available ? "approved" : "pending"}`}>موظف دعم · {m.agent.available ? "متاح" : "غير متاح"}</span>}
                  {m.scope?.tickets === "assigned" && <span className="badge pending">تذاكره فقط</span>}
                  {m.scope?.hide_money && <span className="badge neutral">المبالغ مخفية</span>}
                </div>
              </div>
              {!m.fixed && (
                <div className="row-gap">
                  <span className="muted">{Object.keys(m.perms || {}).length} صفحة</span>
                  <button onClick={() => setEdit(m)}>{canEdit ? "تخصيص" : "عرض"}</button>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {edit && <MemberEditor d={d} member={edit} canEdit={canEdit} onClose={() => setEdit(null)} onSaved={(t) => { setEdit(null); setMsg(t); load(); }} />}
    </>
  );
}

function MemberEditor({ d, member, canEdit, onClose, onSaved }) {
  const [m, setM] = useState(() => ({
    name: member.name || "", role: member.role, perms: { ...(member.perms || {}) },
    scope: { tickets: "all", hide_money: false, hide_contacts: false, ...(member.scope || {}) },
    agent: { ...EMPTY_AGENT, ...(member.agent || {}) },
  }));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const setPerm = (a, v) => setM({ ...m, perms: v ? { ...m.perms, [a]: v } : Object.fromEntries(Object.entries(m.perms).filter(([k]) => k !== a)) });
  const setAll = (v) => setM({ ...m, perms: v ? Object.fromEntries(Object.keys(d.areas).map((a) => [a, a === "staff" && v === "rw" ? "r" : v])) : {} });
  const setScope = (k, v) => setM({ ...m, scope: { ...m.scope, [k]: v } });
  const setAgent = (k, v) => setM({ ...m, agent: { ...m.agent, [k]: v } });
  const toggleIn = (k, v) => setAgent(k, m.agent[k].includes(v) ? m.agent[k].filter((x) => x !== v) : [...m.agent[k], v]);
  const roleDefaults = (role) => ({ ...(d.perms[role] || {}) });
  const isDefault = JSON.stringify(Object.entries(m.perms).sort()) === JSON.stringify(Object.entries(roleDefaults(m.role)).sort());

  async function save() {
    setBusy(true); setErr("");
    try {
      await api.saveStaff({ id: member.id, name: m.name.trim(), role: m.role, perms: isDefault ? null : m.perms, scope: m.scope,
        agent: { ...m.agent, max_active: Number(m.agent.max_active) || 0, order: Number(m.agent.order) || 0 } });
      onSaved("✅ حُفظت صلاحيات العضو — تُطبَّق خلال 30 ثانية");
    } catch (e) {
      setErr(e.detail === "owner_only" ? "إدارة الفريق للمالك فقط" : "تعذّر الحفظ");
    } finally { setBusy(false); }
  }
  async function remove() {
    if (!window.confirm(`إزالة ${m.name || member.id} من الفريق؟ تذاكره المفتوحة تعود للتوزيع.`)) return;
    await api.removeStaff(member.id).catch(() => {});
    onSaved("تمت إزالة العضو");
  }

  return (
    <>
      <div className="overlay" onClick={onClose} />
      <aside className="sheet wide member-editor">
        <div className="sheet-head"><h2>{m.name || member.id}</h2><button onClick={onClose}>إغلاق</button></div>
        <fieldset disabled={!canEdit || busy} className="plain-fieldset">
          <div className="grid-form">
            <label>الاسم<input value={m.name} maxLength={40} onChange={(e) => setM({ ...m, name: e.target.value })} /></label>
            <label>الدور
              <select value={m.role} onChange={(e) => setM({ ...m, role: e.target.value, perms: roleDefaults(e.target.value) })}>
                {Object.entries(d.roles).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </label>
          </div>

          <h3>الصفحات: ماذا يرى وماذا يعدّل</h3>
          <p className="muted small">«مخفي» يعني أن الصفحة لا تظهر له إطلاقًا ولا يصل لبياناتها حتى عبر الرابط. {isDefault ? "حاليًا: صلاحيات الدور الافتراضية." : "حاليًا: صلاحيات مخصّصة."}</p>
          <div className="row-gap">
            <button type="button" onClick={() => setM({ ...m, perms: roleDefaults(m.role) })}>صلاحيات الدور</button>
            <button type="button" onClick={() => setAll("r")}>عرض الكل</button>
            <button type="button" onClick={() => setAll("")}>إخفاء الكل</button>
          </div>
          {AREA_GROUPS.map(([title, areas]) => (
            <div key={title} className="perm-block">
              <span className="nav-group-title">{title}</span>
              {areas.filter((a) => d.areas[a]).map((a) => (
                <div key={a} className="perm-row">
                  <span>{d.areas[a]}</span>
                  <div className="seg" role="radiogroup" aria-label={d.areas[a]}>
                    {LEVELS.filter(([v]) => !(a === "staff" && v === "rw")).map(([v, l]) => (
                      <button type="button" key={v || "none"} role="radio" aria-checked={(m.perms[a] || "") === v}
                        className={(m.perms[a] || "") === v ? `on lvl-${v || "none"}` : ""} onClick={() => setPerm(a, v)}>{l}</button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          ))}

          <h3>ما يراه داخل الصفحات</h3>
          <div className="perm-row">
            <span>التذاكر التي يراها</span>
            <div className="seg">
              <button type="button" className={m.scope.tickets === "all" ? "on" : ""} onClick={() => setScope("tickets", "all")}>كل التذاكر</button>
              <button type="button" className={m.scope.tickets === "assigned" ? "on" : ""} onClick={() => setScope("tickets", "assigned")}>المسندة إليه فقط</button>
            </div>
          </div>
          <label className="check"><input type="checkbox" checked={m.scope.hide_money} onChange={(e) => setScope("hide_money", e.target.checked)} />إخفاء الأرصدة ومبالغ المدفوعات عنه</label>
          <label className="check"><input type="checkbox" checked={m.scope.hide_contacts} onChange={(e) => setScope("hide_contacts", e.target.checked)} />إخفاء أرقام تلجرام للمستخدمين (يظهر آخر 3 أرقام فقط)</label>

          <h3>موظف دعم (يستلم التذاكر المحوّلة بالتوزيع العادل)</h3>
          <label className="check"><input type="checkbox" checked={m.agent.enabled} onChange={(e) => setAgent("enabled", e.target.checked)} />يستلم تذاكر الدعم</label>
          {m.agent.enabled && (
            <>
              <label className="check"><input type="checkbox" checked={m.agent.available} onChange={(e) => setAgent("available", e.target.checked)} />متاح الآن (يمكنه تغييرها بنفسه من صفحة الدعم)</label>
              <div className="grid-form">
                <label>ترتيبه في الدور<input type="number" min="0" max="999" value={m.agent.order} onChange={(e) => setAgent("order", e.target.value)} /></label>
                <label>أقصى تذاكر مفتوحة معًا (0 = بلا حد)<input type="number" min="0" max="200" value={m.agent.max_active} onChange={(e) => setAgent("max_active", e.target.value)} /></label>
              </div>
              <span className="muted small">التخصصات (الذكاء الاصطناعي يصنّف التذكرة ويوجّهها لصاحب التخصص)</span>
              <div className="chips">
                {Object.entries(d.skills || {}).map(([k, v]) => (
                  <button type="button" key={k} className={`chip ${m.agent.skills.includes(k) ? "on" : ""}`} onClick={() => toggleIn("skills", k)}>{v}</button>
                ))}
              </div>
              <span className="muted small">اللغات (فارغ = كل اللغات)</span>
              <div className="chips">
                {Object.entries(LANGS).map(([k, v]) => (
                  <button type="button" key={k} className={`chip ${m.agent.langs.includes(k) ? "on" : ""}`} onClick={() => toggleIn("langs", k)}>{v}</button>
                ))}
              </div>
            </>
          )}
        </fieldset>
        {err && <p className="error-text">{err}</p>}
        {canEdit && (
          <div className="row-gap sticky-actions">
            <button className="primary" disabled={busy} onClick={save}>حفظ</button>
            <button className="danger-ghost" disabled={busy} onClick={remove}>إزالة من الفريق</button>
          </div>
        )}
      </aside>
    </>
  );
}
