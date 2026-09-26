import React, { useEffect, useMemo, useState } from "react";
import { api } from "../api";

const STATUS = { open: "مستلمة", in_progress: "قيد المعالجة", escalated: "مصعّدة للبشري", resolved: "تم الحل", closed: "مغلقة" };
const STATUS_CLS = { open: "pending", in_progress: "pending", escalated: "rejected", resolved: "approved", closed: "neutral" };
const PRIORITY = { critical: "حرجة", medium: "متوسطة", low: "بسيطة" };
const PRIORITY_CLS = { critical: "rejected", medium: "pending", low: "neutral" };
const ROLE = { user: "المستخدم", ai: "المساعد الذكي", agent: "فريق الدعم", system: "النظام" };
const FIX = { resync_account: "إعادة مزامنة الحساب", recheck_payment: "إعادة فحص الدفع", reset_stuck_link: "فك تعليق الربط", set_language: "تغيير اللغة" };
const KIND = { network: "اتصال", server: "خادم", operation: "عملية", ui: "واجهة" };
const when = (ts) => (ts ? new Date(ts * 1000).toLocaleString("ar-u-nu-latn", { dateStyle: "short", timeStyle: "short" }) : "—");
const TABS = [["tickets", "التذاكر"], ["settings", "مركز الدعم والإعدادات"], ["learning", "التعلّم الذاتي"], ["prompt", "System Prompt"], ["kb", "قاعدة المعرفة"], ["fixes", "الإصلاحات الآلية"], ["errors", "سجل الأخطاء"]];

export default function Support({ canWrite }) {
  const [tab, setTab] = useState("tickets");
  return (
    <>
      <div className="topbar"><h1>الدعم الفني الذكي</h1></div>
      <div className="tabs page-tabs">
        {TABS.map(([k, l]) => <button key={k} className={`tab ${tab === k ? "active" : ""}`} onClick={() => setTab(k)}>{l}</button>)}
      </div>
      {tab === "tickets" && <Tickets canWrite={canWrite} />}
      {tab === "settings" && <Settings canWrite={canWrite} />}
      {tab === "learning" && <Learning canWrite={canWrite} />}
      {tab === "prompt" && <Prompt canWrite={canWrite} />}
      {tab === "kb" && <Kb canWrite={canWrite} />}
      {tab === "fixes" && <Fixes />}
      {tab === "errors" && <Errors />}
    </>
  );
}

// ───────────── التذاكر ─────────────
function Tickets({ canWrite }) {
  const [f, setF] = useState({ status: "active", priority: "", q: "" });
  const [data, setData] = useState(null);
  const [open, setOpen] = useState(null);
  const load = () => api.tickets(f).then(setData).catch(() => setData({ rows: [], stats: {} }));
  useEffect(() => {
    const id = setTimeout(load, 250);
    return () => clearTimeout(id);
  }, [f.status, f.priority, f.q]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const id = setInterval(load, 20000);
    return () => clearInterval(id);
  });
  const st = data?.stats || {};
  return (
    <>
      <div className="kpi-grid">
        <div className="kpi accent"><span className="kpi-label">تذاكر مفتوحة</span><span className="kpi-value">{st.open ?? "—"}</span></div>
        <div className="kpi bad"><span className="kpi-label">حرجة مفتوحة</span><span className="kpi-value">{st.critical_open ?? "—"}</span></div>
        <div className="kpi"><span className="kpi-label">مع الفريق البشري</span><span className="kpi-value">{st.escalated ?? "—"}</span></div>
        <div className="kpi ok"><span className="kpi-label">محلولة</span><span className="kpi-value">{st.resolved ?? "—"}</span></div>
        <div className="kpi"><span className="kpi-label">رضا العملاء (CSAT)</span><span className="kpi-value">{st.csat_avg ? `${st.csat_avg}/5` : "—"}</span><span className="kpi-hint">{st.csat_count || 0} تقييم</span></div>
      </div>
      <div className="filters">
        <input className="search" placeholder="بحث: رقم التذكرة، Telegram ID، الموضوع…" value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} />
        <select value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}>
          <option value="active">المفتوحة (كل الحالات النشطة)</option>
          <option value="">كل الحالات</option>
          {Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <select value={f.priority} onChange={(e) => setF({ ...f, priority: e.target.value })}>
          <option value="">كل الأولويات</option>
          {Object.entries(PRIORITY).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </div>
      {!data ? <p className="muted">جارٍ التحميل…</p> : data.rows.length === 0 ? <div className="empty">لا توجد تذاكر مطابقة.</div> : (
        <div className="ticket-list">
          {data.rows.map((r) => (
            <button key={r.id} className={`ticket-row pr-${r.priority}`} onClick={() => setOpen(r.id)}>
              <div className="ticket-top">
                <b className="mono">#{r.id}</b>
                <span className={`badge ${PRIORITY_CLS[r.priority]}`}>{PRIORITY[r.priority]}</span>
                <span className={`badge ${STATUS_CLS[r.status]}`}>{STATUS[r.status]}</span>
                {r.csat?.score && <span className="badge neutral">★ {r.csat.score}</span>}
              </div>
              <div className="ticket-subject">{r.subject || "—"}</div>
              <div className="audit-meta"><span className="mono">{r.uid}</span><span>{r.lang === "ar" ? "عربي" : "English"}</span><span>{when(r.updated_at)}</span><span>ردود المساعد: {r.ai_attempts || 0}</span></div>
            </button>
          ))}
        </div>
      )}
      {open && <TicketSheet id={open} canWrite={canWrite} onClose={() => { setOpen(null); load(); }} />}
    </>
  );
}

function TicketSheet({ id, canWrite, onClose }) {
  const [d, setD] = useState(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const load = () => api.ticket(id).then(setD).catch(() => setErr("تعذّر التحميل"));
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  async function act(fn) {
    setBusy(true); setErr("");
    try { await fn(); await load(); } catch (e) { setErr(e.detail || "فشل الإجراء"); } finally { setBusy(false); }
  }
  const t = d?.ticket;
  const ctx = d?.context;
  return (
    <>
      <div className="overlay" onClick={onClose} />
      <aside className="sheet wide">
        <div className="sheet-head"><h2 className="mono">#{id}</h2><button onClick={onClose}>إغلاق</button></div>
        {!d ? <p className="muted">{err || "جارٍ التحميل…"}</p> : (
          <>
            <div className="row-gap">
              <span className={`badge ${PRIORITY_CLS[t.priority]}`}>{PRIORITY[t.priority]}</span>
              <span className={`badge ${STATUS_CLS[t.status]}`}>{STATUS[t.status]}</span>
              <span className="muted mono">{t.uid}</span>
            </div>
            {t.escalation_summary && <div className="note-box"><b>ملخص التصعيد</b><p>{t.escalation_summary}</p></div>}
            {d.error && <div className="note-box bad"><b>الخطأ المرتبط {d.error.ref}</b><p>{KIND[d.error.kind]} · {d.error.code} · {d.error.message} · الصفحة: {d.error.page || "—"}</p></div>}
            <div className="chat">
              {d.messages.map((m, i) => (
                <div key={i} className={`msg ${m.role}`}>
                  <span className="msg-role">{ROLE[m.role] || m.role} · {when(m.at)}</span>
                  <p>{m.text}</p>
                </div>
              ))}
            </div>
            {canWrite && (
              <div className="reject-box">
                <textarea rows={3} placeholder="اكتب ردك للمستخدم (يصله عبر بوت الدعم فورًا)…" value={text} onChange={(e) => setText(e.target.value)} />
                <div className="row-gap">
                  <button className="primary" disabled={busy || !text.trim()} onClick={() => act(async () => { await api.replyTicket(id, text.trim()); setText(""); })}>إرسال الرد</button>
                  <select value={t.priority} disabled={busy} onChange={(e) => act(() => api.ticketStatus(id, t.status === "resolved" ? "resolved" : t.status, "", e.target.value))} style={{ width: "auto" }}>
                    {Object.entries(PRIORITY).map(([k, v]) => <option key={k} value={k}>أولوية: {v}</option>)}
                  </select>
                  {["in_progress", "resolved", "closed"].filter((s) => s !== t.status).map((s) => (
                    <button key={s} className={s === "resolved" ? "ok-ghost" : ""} disabled={busy} onClick={() => act(() => api.ticketStatus(id, s))}>{STATUS[s]}</button>
                  ))}
                </div>
                {err && <p className="error-text">{err}</p>}
              </div>
            )}
            <h3>بيانات المستخدم (كما يراها المساعد)</h3>
            {ctx && (
              <div>
                <div className="kv"><span>الاسم</span><b>{ctx.nickname || "—"}</b></div>
                <div className="kv"><span>حالة الربط</span><b>{ctx.link_status}</b></div>
                <div className="kv"><span>الاشتراك</span><b>{ctx.subscription?.active ? `فعّال · ${ctx.subscription.expires_in_days} يوم` : "غير فعّال"}</b></div>
                <div className="kv"><span>المزامنة</span><b>{ctx.sync?.state || "—"} {ctx.sync?.last_ok ? `· ${ctx.sync.last_ok}` : ""}</b></div>
                <div className="kv"><span>الرصيد</span><b>{ctx.live ? `${ctx.live.balance} ${ctx.live.currency}` : "—"}</b></div>
                <div className="kv"><span>آخر المدفوعات</span><b>{(ctx.recent_payments || []).map((p) => `${p.method}:${p.status}`).join(" · ") || "—"}</b></div>
                <div className="kv"><span>آخر الأخطاء</span><b>{(ctx.recent_errors || []).map((e) => e.ref).join(" · ") || "—"}</b></div>
              </div>
            )}
            <h3>سجل الحالة</h3>
            <div className="audit-meta" style={{ flexDirection: "column" }}>
              {(t.history || []).map((h, i) => <span key={i}>{when(h.at)} · {STATUS[h.status]} · {h.by}{h.note ? ` · ${h.note}` : ""}</span>)}
            </div>
          </>
        )}
      </aside>
    </>
  );
}

// ───────────── مركز الدعم والإعدادات ─────────────
const LIST_KEYS = ["quick_ar", "quick_en"];
function Settings({ canWrite }) {
  const [c, setC] = useState(null);
  const [gkey, setGkey] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.supportConfig().then(setC).catch(() => setMsg("تعذّر التحميل")); }, []);
  if (!c) return <p className="muted">{msg || "جارٍ التحميل…"}</p>;
  const set = (k) => (e) => setC({ ...c, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const setList = (k) => (e) => setC({ ...c, [k]: e.target.value.split("\n") });
  const setAct = (a) => (e) => setC({ ...c, ai_actions: { ...(c.ai_actions || {}), [a]: e.target.checked } });
  async function save(extra = {}) {
    setBusy(true); setMsg("");
    try {
      const keys = ["enabled", "ai_enabled", "auto_fix_enabled", "csat_enabled", "confirm_actions_enabled", "push_bot_on_reply", "attachments_enabled",
        "sounds_enabled", "learning_enabled", "ai_actions", "welcome_ar", "welcome_en", "support_chat_id", "support_phone", "model", "fallback_models",
        "escalation_threshold", "rate_limit_count", "rate_limit_window", "eta_critical_min", "eta_medium_min", "eta_low_min", ...LIST_KEYS];
      const patch = Object.fromEntries(keys.map((k) => [k, LIST_KEYS.includes(k) ? (c[k] || []).map((x) => x.trim()).filter(Boolean) : c[k]]));
      const r = await api.saveSupportConfig({ ...patch, ...extra });
      setC({ ...c, ...r });
      setGkey("");
      setMsg("✓ تم الحفظ — يُطبَّق فورًا في التطبيق");
    } catch (e) {
      setMsg(`✗ ${e.detail || "فشل الحفظ"}`);
    } finally { setBusy(false); }
  }
  const actions = c.ai_actions || {};
  return (
    <>
      <div className="panel">
        <h2>مركز الدعم داخل التطبيق</h2>
        <p className="muted">الدعم أصبح صفحة كاملة داخل الـ Mini App (سماعة الرأس 🎧، الإعدادات، رسائل الأخطاء، وزر «فتح مركز الدعم» في البوت). لا بوت دعم منفصل ولا حسابات تلجرام.</p>
        <label className="check"><input type="checkbox" checked={!!c.enabled} onChange={set("enabled")} disabled={!canWrite} />تشغيل مركز الدعم</label>
        <label className="check"><input type="checkbox" checked={c.attachments_enabled !== false} onChange={set("attachments_enabled")} disabled={!canWrite} />السماح بإرفاق الصور (لقطات شاشة ≤ 3MB — المساعد يقرأها)</label>
        <label className="check"><input type="checkbox" checked={c.sounds_enabled !== false} onChange={set("sounds_enabled")} disabled={!canWrite} />أصوات الردود في التطبيق</label>
        <label className="check"><input type="checkbox" checked={c.push_bot_on_reply !== false} onChange={set("push_bot_on_reply")} disabled={!canWrite} />تنبيه المستخدم في البوت عند رد الموظف أو حل التذكرة (مع زر يفتح مركز الدعم)</label>
        <label className="check"><input type="checkbox" checked={!!c.csat_enabled} onChange={set("csat_enabled")} disabled={!canWrite} />طلب تقييم الرضا بعد الحل (CSAT)</label>
        <div className="grid-form">
          <label>رسالة الترحيب (عربي)<textarea rows={3} value={c.welcome_ar || ""} onChange={set("welcome_ar")} disabled={!canWrite} /></label>
          <label>رسالة الترحيب (English)<textarea rows={3} dir="ltr" value={c.welcome_en || ""} onChange={set("welcome_en")} disabled={!canWrite} /></label>
          <label>الردود السريعة (عربي — سطر لكل رد، حتى 8)<textarea rows={4} value={(c.quick_ar || []).join("\n")} onChange={setList("quick_ar")} disabled={!canWrite} /></label>
          <label>الردود السريعة (English)<textarea rows={4} dir="ltr" value={(c.quick_en || []).join("\n")} onChange={setList("quick_en")} disabled={!canWrite} /></label>
          <label>حساب الموظف لتنبيهات التصعيد (Telegram ID)
            <input className="mono" placeholder="مثل 123456789" value={c.support_chat_id || ""} onChange={set("support_chat_id")} disabled={!canWrite} />
          </label>
          <label>رقم هاتف الدعم (يظهر في التطبيق)
            <input className="mono" placeholder="+966…" value={c.support_phone || ""} onChange={set("support_phone")} disabled={!canWrite} />
          </label>
        </div>
        <p className="muted">التصعيدات تصل فورًا لحساب الموظف في البوت مع الأولوية والملخص، والرد يكون من «التذاكر» هنا فيظهر للمستخدم داخل التطبيق مع صوت تنبيه.</p>
      </div>

      <div className="panel">
        <h2>المساعد الذكي وصلاحياته</h2>
        <p className="muted">المحرك: Google Gemini (قابل للتغيير) · الحالة: {c.ai_available
          ? <b style={{ color: "var(--ok)" }}>متصل ({c.has_gemini_key ? "مفتاح من اللوحة" : "GEMINI_API_KEY من .env"})</b>
          : <b style={{ color: "var(--bad)" }}>غير مضبوط — أضف مفتاح Gemini أدناه (يعمل حاليًا بقاعدة المعرفة + التحويل للبشري)</b>}</p>
        <div className="grid-form">
          <label>مفتاح Gemini API (من aistudio.google.com)
            <input type="password" autoComplete="off" dir="ltr" placeholder={c.has_gemini_key ? "مضبوط ومشفّر — اكتب مفتاحًا جديدًا للتغيير" : c.gemini_env_key ? "يُستخدم مفتاح .env — اختياري" : "AIza…"} value={gkey} onChange={(e) => setGkey(e.target.value.trim())} disabled={!canWrite} />
          </label>
          <label>النموذج<input className="mono" dir="ltr" placeholder={c.model_default} value={c.model} onChange={set("model")} disabled={!canWrite} /></label>
          <label>نماذج احتياطية عند الازدحام (بفواصل)
            <input className="mono" dir="ltr" placeholder="gemini-flash-lite-latest, gemini-2.5-flash" value={Array.isArray(c.fallback_models) ? c.fallback_models.join(", ") : c.fallback_models || ""}
              onChange={(e) => setC({ ...c, fallback_models: e.target.value })} disabled={!canWrite} />
          </label>
        </div>
        <label className="check"><input type="checkbox" checked={!!c.ai_enabled} onChange={set("ai_enabled")} disabled={!canWrite} />الرد الآلي بالمساعد الذكي</label>
        <label className="check"><input type="checkbox" checked={!!c.auto_fix_enabled} onChange={set("auto_fix_enabled")} disabled={!canWrite} />السماح بالإصلاح الذاتي (مفتاح رئيسي)</label>
        <div className="perm-grid">
          {(c.fix_actions || Object.keys(FIX)).map((a) => (
            <label key={a} className="check"><input type="checkbox" checked={actions[a] !== false} onChange={setAct(a)} disabled={!canWrite || !c.auto_fix_enabled} />{FIX[a] || a}</label>
          ))}
        </div>
        <label className="check"><input type="checkbox" checked={c.confirm_actions_enabled !== false} onChange={set("confirm_actions_enabled")} disabled={!canWrite} />الإجراءات الحساسة (إلغاء الربط، ربط حساب جديد) بعد تأكيد «نعم / لا» من المستخدم</label>
        <label className="check"><input type="checkbox" checked={c.learning_enabled !== false} onChange={set("learning_enabled")} disabled={!canWrite} />التعلّم الذاتي: كل تذكرة محلولة تقترح سؤالًا وجوابًا لقاعدة المعرفة (تعتمدها أنت من «التعلّم الذاتي»)</label>
        <div className="grid-form">
          <label>التصعيد التلقائي بعد (ردود بلا حل)<input type="number" min="1" max="10" value={c.escalation_threshold} onChange={set("escalation_threshold")} disabled={!canWrite} /></label>
          <label>حد الرسائل (Rate limit)<input type="number" min="2" max="60" value={c.rate_limit_count} onChange={set("rate_limit_count")} disabled={!canWrite} /></label>
          <label>خلال (ثانية)<input type="number" min="10" max="3600" value={c.rate_limit_window} onChange={set("rate_limit_window")} disabled={!canWrite} /></label>
        </div>
        <h3>وقت الاستجابة المتوقع (يظهر مع الرد الأولي الفوري)</h3>
        <div className="grid-form">
          <label>حرجة (دقيقة)<input type="number" value={c.eta_critical_min} onChange={set("eta_critical_min")} disabled={!canWrite} /></label>
          <label>متوسطة (دقيقة)<input type="number" value={c.eta_medium_min} onChange={set("eta_medium_min")} disabled={!canWrite} /></label>
          <label>بسيطة (دقيقة)<input type="number" value={c.eta_low_min} onChange={set("eta_low_min")} disabled={!canWrite} /></label>
        </div>
      </div>
      {canWrite && (
        <div className="row-gap sticky-save">
          <button className="primary" disabled={busy} onClick={() => save(gkey ? { gemini_api_key: gkey } : {})}>حفظ كل الإعدادات</button>
          {c.has_gemini_key && <button className="danger-ghost" disabled={busy} onClick={() => save({ gemini_api_key: "" })}>حذف مفتاح Gemini المحفوظ</button>}
        </div>
      )}
      {msg && <p className={msg.startsWith("✗") ? "error-text" : "muted"}>{msg}</p>}
    </>
  );
}

// ───────────── التعلّم الذاتي: اقتراحات من التذاكر المحلولة ─────────────
function Learning({ canWrite }) {
  const [rows, setRows] = useState(null);
  const [edit, setEdit] = useState({});
  const [msg, setMsg] = useState("");
  const load = () => api.kbSuggestions().then((r) => setRows(r.rows)).catch(() => setMsg("تعذّر التحميل"));
  useEffect(() => { load(); }, []);
  if (!rows) return <p className="muted">{msg || "جارٍ التحميل…"}</p>;
  const val = (r, k) => (edit[r.id]?.[k] ?? r[k]);
  const change = (r, k) => (e) => setEdit({ ...edit, [r.id]: { ...(edit[r.id] || {}), [k]: e.target.value } });
  async function approve(r) {
    try {
      await api.approveSuggestion(r.id, val(r, "q").trim().slice(0, 400), val(r, "a").trim().slice(0, 1500));
      setMsg("✓ أُضيفت لقاعدة المعرفة — يستخدمها المساعد من الرسالة التالية");
      load();
    } catch (e) { setMsg(`✗ ${e.detail || "فشل"}`); }
  }
  async function reject(r) {
    await api.rejectSuggestion(r.id).catch(() => {});
    load();
  }
  return (
    <>
      <div className="panel">
        <h2>التعلّم من التذاكر المحلولة</h2>
        <p className="muted">كل تذكرة تُحل يُستخرج منها سؤال المستخدم والجواب الذي حلّ المشكلة. راجع الصياغة ثم اعتمدها لتصبح جزءًا من معرفة المساعد (مرتبة حسب تقييم المستخدم).</p>
        {msg && <p className={msg.startsWith("✗") ? "error-text" : "muted"}>{msg}</p>}
      </div>
      {rows.length === 0 ? <div className="empty">لا اقتراحات جديدة — ستظهر هنا بعد حل التذاكر.</div> : (
        <div className="audit-list">
          {rows.map((r) => (
            <div key={r.id} className="audit">
              <div className="audit-top">
                <b className="mono">#{r.ticket}</b>
                <span className="muted">{r.source === "agent" ? "رد موظف" : "رد المساعد"} · {when(r.at)}</span>
                {r.score ? <span className={`badge ${r.score >= 4 ? "approved" : r.score <= 2 ? "rejected" : "pending"}`}>{"★".repeat(r.score)}</span> : <span className="badge neutral">بلا تقييم</span>}
              </div>
              <label>السؤال<textarea rows={2} value={val(r, "q")} onChange={change(r, "q")} disabled={!canWrite} dir="auto" /></label>
              <label>الجواب المعتمد<textarea rows={4} value={val(r, "a")} onChange={change(r, "a")} disabled={!canWrite} dir="auto" /></label>
              {canWrite && (
                <div className="row-gap">
                  <button className="primary" onClick={() => approve(r)}>اعتماد وإضافة للمعرفة</button>
                  <button className="danger-ghost" onClick={() => reject(r)}>تجاهل</button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </>
  );
}

// ───────────── System Prompt ─────────────
function Prompt({ canWrite }) {
  const [c, setC] = useState(null);
  const [text, setText] = useState("");
  const [msg, setMsg] = useState("");
  useEffect(() => { api.supportConfig().then((r) => { setC(r); setText(r.system_prompt); }); }, []);
  if (!c) return <p className="muted">جارٍ التحميل…</p>;
  async function save(value) {
    try {
      const r = await api.saveSupportConfig({ system_prompt: value });
      setC({ ...c, ...r }); setText(r.system_prompt); setMsg("✓ تم الحفظ — يُطبَّق على الرسالة التالية فورًا");
    } catch (e) { setMsg(`✗ ${e.detail || "فشل الحفظ"}`); }
  }
  return (
    <div className="panel">
      <div className="topbar"><h2>System Prompt لشات الدعم</h2><span className={`badge ${c.prompt_is_default ? "approved" : "pending"}`}>{c.prompt_is_default ? "النص الافتراضي" : "مخصّص"}</span></div>
      <p className="muted">يحدد: أسلوب الرد والنبرة، متى يعدّل البيانات (إصلاح ذاتي)، متى يحوّل للبشري، تصنيف الأولوية، والتعامل مع الأخطاء. البيانات الشخصية تصل للمساعد عبر أدوات آمنة لا عبر هذا النص.</p>
      <textarea className="big-text mono prompt-box" rows={26} value={text} onChange={(e) => setText(e.target.value)} disabled={!canWrite} dir="auto" />
      {canWrite && (
        <div className="row-gap">
          <button className="primary" onClick={() => save(text)}>حفظ</button>
          <button onClick={() => { setText(c.default_prompt); save(""); }}>استعادة النص الافتراضي</button>
          <span className="muted">{text.length.toLocaleString("en")} حرف</span>
        </div>
      )}
      {msg && <p className={msg.startsWith("✗") ? "error-text" : "muted"}>{msg}</p>}
    </div>
  );
}

// ───────────── قاعدة المعرفة ─────────────
function Kb({ canWrite }) {
  const [rows, setRows] = useState(null);
  const [q, setQ] = useState("");
  const [a, setA] = useState("");
  const [search, setSearch] = useState("");
  const load = () => api.kb().then((r) => setRows(r.rows));
  useEffect(() => { load(); }, []);
  const shown = useMemo(() => (rows || []).filter((r) => !search || `${r.q} ${r.a}`.toLowerCase().includes(search.toLowerCase())), [rows, search]);
  return (
    <>
      {canWrite && (
        <div className="panel">
          <h2>إضافة معلومة</h2>
          <p className="muted">يبحث المساعد هنا أولًا قبل التصعيد، ويُجيب منها مباشرة إن تعطّل الذكاء الاصطناعي.</p>
          <input placeholder="السؤال / الكلمات المفتاحية (عربي وإنجليزي)" value={q} onChange={(e) => setQ(e.target.value)} />
          <textarea rows={3} placeholder="الإجابة المعتمدة" value={a} onChange={(e) => setA(e.target.value)} />
          <div><button className="primary" disabled={q.trim().length < 3 || a.trim().length < 3} onClick={async () => { await api.addKb(q.trim(), a.trim()); setQ(""); setA(""); load(); }}>إضافة</button></div>
        </div>
      )}
      <div className="filters"><input className="search" placeholder="بحث في قاعدة المعرفة…" value={search} onChange={(e) => setSearch(e.target.value)} /></div>
      <div className="audit-list">
        {shown.map((r) => (
          <div key={r.id} className="audit">
            <div className="audit-top"><b>{r.q}</b>{r.builtin ? <span className="badge neutral">أساسية</span> : canWrite && <button className="danger-ghost" onClick={async () => { await api.deleteKb(r.id); load(); }}>حذف</button>}</div>
            <span className="muted">{r.a}</span>
          </div>
        ))}
      </div>
    </>
  );
}

// ───────────── سجل الإصلاحات الآلية ─────────────
function Fixes() {
  const [rows, setRows] = useState(null);
  useEffect(() => { api.fixes().then((r) => setRows(r.rows)); }, []);
  if (!rows) return <p className="muted">جارٍ التحميل…</p>;
  if (!rows.length) return <div className="empty">لم ينفّذ المساعد أي إصلاح بعد.</div>;
  return (
    <div className="scrollx">
      <table className="list keep">
        <thead><tr><th>الوقت</th><th>الإجراء</th><th>المستخدم</th><th>التذكرة</th><th>النتيجة</th><th>قبل ← بعد</th></tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td className="mono">{when(r.at)}</td>
              <td>{FIX[r.action] || r.action}</td>
              <td className="mono">{r.uid}</td>
              <td className="mono">{r.ticket ? `#${r.ticket}` : "—"}</td>
              <td><span className={`badge ${r.result?.ok ? "approved" : "rejected"}`}>{r.result?.ok ? "نجح" : r.result?.reason || "لم يُنفّذ"}</span></td>
              <td className="mono muted">{JSON.stringify(r.before || {})} ← {JSON.stringify(r.after || {})}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ───────────── سجل الأخطاء ─────────────
function Errors() {
  const [f, setF] = useState({ kind: "", q: "" });
  const [rows, setRows] = useState(null);
  useEffect(() => {
    const id = setTimeout(() => api.errors(f).then((r) => setRows(r.rows)), 250);
    return () => clearTimeout(id);
  }, [f.kind, f.q]);
  return (
    <>
      <div className="filters">
        <input className="search" placeholder="بحث: ERR-…، Telegram ID، رسالة الخطأ، الصفحة…" value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} />
        <select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
          <option value="">كل الأنواع</option>
          {Object.entries(KIND).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </div>
      {!rows ? <p className="muted">جارٍ التحميل…</p> : rows.length === 0 ? <div className="empty">لا أخطاء مسجّلة.</div> : (
        <div className="scrollx">
          <table className="list keep">
            <thead><tr><th>المرجع</th><th>الوقت</th><th>النوع</th><th>الأولوية</th><th>المستخدم</th><th>الصفحة</th><th>الرمز والرسالة</th><th>الاتصال</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.ref}>
                  <td className="mono">{r.ref}</td>
                  <td className="mono">{when(r.at)}</td>
                  <td>{KIND[r.kind] || r.kind}{r.source === "server" ? " (خادم)" : ""}</td>
                  <td><span className={`badge ${PRIORITY_CLS[r.priority]}`}>{PRIORITY[r.priority]}</span></td>
                  <td className="mono">{r.uid || "—"}</td>
                  <td>{r.page || "—"}</td>
                  <td><span className="mono">{r.code}</span> {r.message}</td>
                  <td>{r.online === false ? "غير متصل" : r.online ? "متصل" : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
