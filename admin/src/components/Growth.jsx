import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import Funnel from "./Funnel";

const when = (ts) => (ts ? new Date(ts * 1000).toLocaleString("ar-u-nu-latn", { dateStyle: "short", timeStyle: "short" }) : "—");
const toTs = (v) => (v ? new Date(v).getTime() / 1000 : 0);
const toLocal = (ts) => (ts ? new Date(ts * 1000 - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16) : "");
const OFFER = { discount: "خصم %", free_days: "أيام مجانية" };
const GIFT = { days: "أيام اشتراك فورية", discount: "خصم %", free_days: "أيام مع الاشتراك القادم", scratch: "بطاقة خدش" };
const SOURCES = { instagram: "Instagram", tiktok: "TikTok", facebook: "Facebook", x: "X", youtube: "YouTube", telegram: "Telegram", google: "Google Ads", influencer: "مؤثر", other: "أخرى" };
const TABS = [["funnel", "القمع والحملات"], ["coupons", "الكوبونات"], ["gifts", "روابط الهدايا"], ["auto", "الأتمتة والاسترجاع"]];

function copy(text) {
  navigator.clipboard?.writeText(text).catch(() => {});
}

function useMsg() {
  const [msg, setMsg] = useState("");
  const run = async (fn, ok) => {
    setMsg("");
    try {
      const r = await fn();
      if (ok) setMsg(`✓ ${typeof ok === "function" ? ok(r) : ok}`);
      return r;
    } catch (e) {
      setMsg(`✗ ${e.detail || "فشلت العملية"}`);
      return null;
    }
  };
  const view = msg ? <p className={msg.startsWith("✗") ? "error-text" : "muted"}>{msg}</p> : null;
  return [run, view];
}

/** النمو والتسويق: قمع كل حملة، روابط تتبّع للإعلانات، كوبونات، روابط هدايا، ورسائل استرجاع تلقائية. */
export default function Growth({ canWrite }) {
  const [tab, setTab] = useState("funnel");
  return (
    <>
      <div className="topbar"><h1>النمو والتسويق</h1></div>
      <div className="tabs page-tabs">
        {TABS.map(([k, l]) => <button key={k} className={`tab ${tab === k ? "active" : ""}`} onClick={() => setTab(k)}>{l}</button>)}
      </div>
      {tab === "funnel" && <Campaigns canWrite={canWrite} />}
      {tab === "coupons" && <Coupons canWrite={canWrite} />}
      {tab === "gifts" && <Gifts canWrite={canWrite} />}
      {tab === "auto" && <Automations canWrite={canWrite} />}
    </>
  );
}

// ───────────── القمع والحملات ─────────────
function Campaigns({ canWrite }) {
  const [rows, setRows] = useState(null);
  const [all, setAll] = useState(null);
  const [pick, setPick] = useState("");
  const [form, setForm] = useState({ slug: "", name: "", source: "instagram", gift_code: "" });
  const [run, msg] = useMsg();
  const load = useCallback(() => {
    api.campaigns().then((r) => setRows(r.rows)).catch(() => setRows([]));
    api.funnel().then(setAll).catch(() => {});
  }, []);
  useEffect(load, [load]);
  const current = pick ? rows?.find((r) => r.id === pick)?.funnel : all;

  async function save(e) {
    e.preventDefault();
    if (await run(() => api.saveCampaign(form), "تم حفظ الحملة")) {
      setForm({ slug: "", name: "", source: "instagram", gift_code: "" });
      load();
    }
  }

  return (
    <>
      <div className="panel">
        <div className="field-row">
          <h2>قمع التحويل</h2>
          <select style={{ width: "auto" }} value={pick} onChange={(e) => setPick(e.target.value)}>
            <option value="">كل المستخدمين</option>
            {(rows || []).map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
          </select>
        </div>
        {current ? <Funnel f={current} /> : <p className="muted">جارٍ التحميل…</p>}
      </div>

      {canWrite && (
        <form className="panel" onSubmit={save}>
          <h2>حملة جديدة (رابط تتبّع لكل إعلان أو منصة)</h2>
          <div className="grid-form">
            <label>المعرّف في الرابط (a-z 0-9 -)<input className="mono" dir="ltr" required placeholder="insta-june" value={form.slug} onChange={(e) => setForm({ ...form, slug: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "") })} /></label>
            <label>الاسم<input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
            <label>المنصة
              <select value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })}>
                {Object.entries(SOURCES).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select>
            </label>
            <label>هدية ترحيبية تلقائية (كود هدية، اختياري)<input className="mono" dir="ltr" value={form.gift_code} onChange={(e) => setForm({ ...form, gift_code: e.target.value.toUpperCase() })} /></label>
          </div>
          <div><button className="primary">حفظ الحملة</button></div>
        </form>
      )}
      {msg}

      {rows && rows.length === 0 && <div className="empty">لا حملات بعد. أنشئ حملة لكل إعلان لتعرف أي منصة تجلب مشتركين فعليًا.</div>}
      {rows && rows.length > 0 && (
        <div className="scrollx">
          <table className="list keep">
            <thead><tr><th>الحملة</th><th>نقرات</th><th>فتحوا</th><th>ربطوا</th><th>دفعوا</th><th>الإيراد</th><th>الرابط</th><th /></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td><b>{r.name}</b><div className="muted">{SOURCES[r.source] || r.source}{r.gift_code ? ` · 🎁 ${r.gift_code}` : ""}</div></td>
                  <td className="mono">{r.clicks || 0}</td>
                  <td className="mono">{r.funnel?.opened ?? 0}</td>
                  <td className="mono">{r.funnel?.linked ?? 0}</td>
                  <td className="mono">{r.funnel?.paid ?? 0}{r.funnel?.rates?.pay != null ? <span className="muted"> ({r.funnel.rates.pay}%)</span> : null}</td>
                  <td className="mono">${Number(r.funnel?.revenue_usd || 0).toLocaleString("en-US")}</td>
                  <td>{r.link ? <button onClick={() => copy(r.link)} title={r.link}>نسخ الرابط</button> : <span className="muted">—</span>}</td>
                  <td>{canWrite && <button className="danger-ghost" onClick={async () => window.confirm(`حذف الحملة ${r.name}؟ (يبقى المستخدمون منسوبين لها)`) && (await run(() => api.deleteCampaign(r.id), "حُذفت")) && load()}>حذف</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

// ───────────── الكوبونات ─────────────
const EMPTY_COUPON = { code: "", type: "discount", value: 20, max_uses: 100, expires: "", valid_hours: 72, campaign: "", note: "", active: true };

function Coupons({ canWrite }) {
  const [rows, setRows] = useState(null);
  const [form, setForm] = useState(null);
  const [run, msg] = useMsg();
  const load = useCallback(() => api.coupons().then((r) => setRows(r.rows)).catch(() => setRows([])), []);
  useEffect(() => { load(); }, [load]);

  async function save(e) {
    e.preventDefault();
    const { expires, ...rest } = form;
    if (await run(() => api.saveCoupon({ ...rest, expires_at: toTs(expires) }), "تم حفظ الكوبون")) {
      setForm(null);
      load();
    }
  }

  return (
    <>
      <div className="panel">
        <p className="muted">المستخدم يكتب الكود في شاشة الباقات ← يتحوّل لمكافأة في محفظته تُطبَّق تلقائيًا على كل طرق الدفع. مرة واحدة لكل مستخدم.</p>
        {canWrite && !form && <div><button className="primary" onClick={() => setForm({ ...EMPTY_COUPON })}>+ كوبون جديد</button></div>}
      </div>
      {form && (
        <form className="panel" onSubmit={save}>
          <h2>{rows?.some((r) => r.id === form.code) ? `تعديل ${form.code}` : "كوبون جديد"}</h2>
          <div className="grid-form">
            <label>الكود<input className="mono" dir="ltr" required value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, "") })} /></label>
            <label>النوع
              <select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
                {Object.entries(OFFER).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select>
            </label>
            <label>{form.type === "discount" ? "نسبة الخصم (1–90)" : "عدد الأيام (1–365)"}<input className="mono" type="number" min="1" max={form.type === "discount" ? 90 : 365} value={form.value} onChange={(e) => setForm({ ...form, value: Number(e.target.value) })} /></label>
            <label>أقصى عدد استخدامات (0 = بلا حد)<input className="mono" type="number" min="0" value={form.max_uses} onChange={(e) => setForm({ ...form, max_uses: Number(e.target.value) })} /></label>
            <label>ينتهي في (اختياري)<input type="datetime-local" value={form.expires} onChange={(e) => setForm({ ...form, expires: e.target.value })} /></label>
            <label>صلاحية المكافأة بعد الاسترداد (ساعة)<input className="mono" type="number" min="1" max="720" value={form.valid_hours} onChange={(e) => setForm({ ...form, valid_hours: Number(e.target.value) })} /></label>
            <label>الحملة (اختياري)<input className="mono" dir="ltr" value={form.campaign} onChange={(e) => setForm({ ...form, campaign: e.target.value })} /></label>
            <label>ملاحظة داخلية<input value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} /></label>
          </div>
          <label className="check"><input type="checkbox" checked={form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} /> مفعّل</label>
          <div className="row-gap"><button className="primary">حفظ</button><button type="button" onClick={() => setForm(null)}>إلغاء</button></div>
        </form>
      )}
      {msg}
      {rows && rows.length === 0 && <div className="empty">لا كوبونات بعد.</div>}
      {rows && rows.length > 0 && (
        <div className="scrollx">
          <table className="list keep">
            <thead><tr><th>الكود</th><th>القيمة</th><th>الاستخدام</th><th>ينتهي</th><th>الحالة</th><th /></tr></thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id}>
                  <td><b className="mono">{c.id}</b>{c.note && <div className="muted">{c.note}</div>}</td>
                  <td>{c.type === "discount" ? `${c.value}%` : `${c.value} يوم`}</td>
                  <td className="mono">{c.used_count || 0}{c.max_uses ? ` / ${c.max_uses}` : ""}</td>
                  <td>{c.expires_at ? when(c.expires_at) : "بلا حد"}</td>
                  <td>
                    {(() => {
                      const exp = c.expires_at && c.expires_at < Date.now() / 1000;
                      const full = c.max_uses && (c.used_count || 0) >= c.max_uses;
                      const [l, cls] = !c.active ? ["موقوف", "neutral"] : exp ? ["منتهي", "rejected"] : full ? ["نفد", "rejected"] : ["فعّال", "approved"];
                      return <span className={`badge ${cls}`}>{l}</span>;
                    })()}
                  </td>
                  <td className="row-gap">
                    <button onClick={() => copy(c.id)}>نسخ</button>
                    {canWrite && <button onClick={() => setForm({ ...EMPTY_COUPON, ...c, code: c.id, expires: toLocal(c.expires_at) })}>تعديل</button>}
                    {canWrite && <button className="danger-ghost" onClick={async () => window.confirm(`حذف الكوبون ${c.id}؟`) && (await run(() => api.deleteCoupon(c.id), "حُذف")) && load()}>حذف</button>}
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

// ───────────── روابط الهدايا ─────────────
const EMPTY_GIFT = { code: "", title: "", type: "days", value: 7, max_claims: 50, expires: "", valid_hours: 72, campaign: "", active: true };

function Gifts({ canWrite }) {
  const [rows, setRows] = useState(null);
  const [form, setForm] = useState(null);
  const [run, msg] = useMsg();
  const load = useCallback(() => api.gifts().then((r) => setRows(r.rows)).catch(() => setRows([])), []);
  useEffect(() => { load(); }, [load]);

  async function save(e) {
    e.preventDefault();
    const { expires, ...rest } = form;
    if (await run(() => api.saveGift({ ...rest, expires_at: toTs(expires) }), "تم إنشاء رابط الهدية")) {
      setForm(null);
      load();
    }
  }

  return (
    <>
      <div className="panel">
        <p className="muted">رابط تشاركه في أي مكان (قناة، مؤثر، رسالة خاصة): من يفتحه يحصل على الهدية فورًا — مرة لكل مستخدم وبحد أقصى للمطالبات.</p>
        {canWrite && !form && <div><button className="primary" onClick={() => setForm({ ...EMPTY_GIFT })}>+ رابط هدية جديد</button></div>}
      </div>
      {form && (
        <form className="panel" onSubmit={save}>
          <h2>رابط هدية</h2>
          <div className="grid-form">
            <label>الاسم الداخلي<input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></label>
            <label>الكود (فارغ = توليد تلقائي)<input className="mono" dir="ltr" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, "") })} /></label>
            <label>نوع الهدية
              <select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
                {Object.entries(GIFT).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select>
            </label>
            {form.type !== "scratch" && (
              <label>{form.type === "discount" ? "نسبة الخصم" : "عدد الأيام"}<input className="mono" type="number" min="1" max={form.type === "discount" ? 90 : 365} value={form.value} onChange={(e) => setForm({ ...form, value: Number(e.target.value) })} /></label>
            )}
            <label>أقصى عدد مطالبات (0 = بلا حد)<input className="mono" type="number" min="0" value={form.max_claims} onChange={(e) => setForm({ ...form, max_claims: Number(e.target.value) })} /></label>
            <label>ينتهي في (اختياري)<input type="datetime-local" value={form.expires} onChange={(e) => setForm({ ...form, expires: e.target.value })} /></label>
            {(form.type === "discount" || form.type === "free_days") && (
              <label>صلاحية المكافأة (ساعة)<input className="mono" type="number" min="1" max="720" value={form.valid_hours} onChange={(e) => setForm({ ...form, valid_hours: Number(e.target.value) })} /></label>
            )}
          </div>
          <label className="check"><input type="checkbox" checked={form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} /> مفعّل</label>
          <div className="row-gap"><button className="primary">حفظ</button><button type="button" onClick={() => setForm(null)}>إلغاء</button></div>
        </form>
      )}
      {msg}
      {rows && rows.length === 0 && <div className="empty">لا روابط هدايا بعد.</div>}
      {rows && rows.length > 0 && (
        <div className="scrollx">
          <table className="list keep">
            <thead><tr><th>الهدية</th><th>المطالبات</th><th>ينتهي</th><th>الروابط</th><th /></tr></thead>
            <tbody>
              {rows.map((g) => (
                <tr key={g.id}>
                  <td><b>{g.title || g.id}</b><div className="muted">{GIFT[g.type]}{g.type !== "scratch" ? ` · ${g.type === "discount" ? `${g.value}%` : `${g.value} يوم`}` : ""} · <span className="mono">{g.id}</span></div></td>
                  <td className="mono">{g.claims || 0}{g.max_claims ? ` / ${g.max_claims}` : ""}</td>
                  <td>{g.expires_at ? when(g.expires_at) : "بلا حد"}{!g.active && <span className="badge neutral" style={{ marginInlineStart: 6 }}>موقوف</span>}</td>
                  <td className="row-gap">
                    {g.bot_link && <button onClick={() => copy(g.bot_link)} title={g.bot_link}>رابط البوت</button>}
                    {g.app_link && <button onClick={() => copy(g.app_link)} title={g.app_link}>رابط التطبيق</button>}
                  </td>
                  <td className="row-gap">
                    {canWrite && <button onClick={() => setForm({ ...EMPTY_GIFT, ...g, code: g.id, expires: toLocal(g.expires_at) })}>تعديل</button>}
                    {canWrite && <button className="danger-ghost" onClick={async () => window.confirm("حذف رابط الهدية؟ سيتوقف فورًا.") && (await run(() => api.deleteGift(g.id), "حُذف")) && load()}>حذف</button>}
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

// ───────────── الأتمتة السلوكية ─────────────
function Automations({ canWrite }) {
  const [d, setD] = useState(null);
  const [edit, setEdit] = useState(null);
  const [run, msg] = useMsg();
  const load = useCallback(() => api.automations().then(setD).catch(() => setD({ rows: [], triggers: {}, log: [] })), []);
  useEffect(() => { load(); }, [load]);
  if (!d) return <p className="muted">جارٍ التحميل…</p>;

  async function save(e) {
    e.preventDefault();
    const { id, ...data } = edit;
    if (await run(() => api.saveAutomation(id, data), "تم الحفظ")) {
      setEdit(null);
      load();
    }
  }
  const toggle = async (r) => (await run(() => api.saveAutomation(r.id, { ...r, enabled: !r.enabled }), r.enabled ? "أُوقفت" : "فُعّلت")) && load();
  const names = Object.fromEntries(d.rows.map((r) => [r.id, r.name]));

  return (
    <>
      <div className="panel">
        <p className="muted">
          قواعد «سلوك ← انتظار ← رسالة + عرض خاص» تعمل تلقائيًا كل ساعة. كل مستخدم يستلم رسالة واحدة كحد أقصى لكل دورة، والعرض يُضاف لمحفظة مكافآته
          فيُطبَّق عند الدفع. المتغيرات في النص: <span className="mono">{"{name} {offer} {hours}"}</span>. كل القواعد تبدأ موقوفة حتى تفعّلها.
        </p>
        {canWrite && (
          <div className="row-gap">
            <button className="primary" onClick={() => setEdit({ id: `rule_${Date.now().toString(36)}`, name: "", trigger: "inactive", delay_hours: 72, enabled: false, offer_type: "none", offer_value: 0, offer_hours: 48, via_bot: true, message_ar: "", message_en: "" })}>+ قاعدة جديدة</button>
            <button onClick={async () => (await run(() => api.runAutomations(), (r) => `أُرسلت ${r.sent} رسالة`)) && load()}>تشغيل الآن</button>
          </div>
        )}
      </div>
      {msg}
      {edit && (
        <form className="panel" onSubmit={save}>
          <h2>{edit.name || "قاعدة جديدة"}</h2>
          <div className="grid-form">
            <label>الاسم<input required value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></label>
            <label>عندما
              <select value={edit.trigger} onChange={(e) => setEdit({ ...edit, trigger: e.target.value })}>
                {Object.entries(d.triggers).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select>
            </label>
            <label>بعد (ساعة)<input className="mono" type="number" min="1" max="2160" value={edit.delay_hours} onChange={(e) => setEdit({ ...edit, delay_hours: Number(e.target.value) })} /></label>
            <label>العرض
              <select value={edit.offer_type} onChange={(e) => setEdit({ ...edit, offer_type: e.target.value })}>
                <option value="none">بدون عرض</option>
                {Object.entries(OFFER).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select>
            </label>
            {edit.offer_type !== "none" && (
              <>
                <label>القيمة<input className="mono" type="number" min="1" max={edit.offer_type === "discount" ? 90 : 60} value={edit.offer_value} onChange={(e) => setEdit({ ...edit, offer_value: Number(e.target.value) })} /></label>
                <label>صلاحية العرض (ساعة)<input className="mono" type="number" min="1" max="720" value={edit.offer_hours} onChange={(e) => setEdit({ ...edit, offer_hours: Number(e.target.value) })} /></label>
              </>
            )}
          </div>
          <div className="grid-form">
            <label>الرسالة (عربي)<textarea rows={4} value={edit.message_ar} onChange={(e) => setEdit({ ...edit, message_ar: e.target.value })} /></label>
            <label>Message (English)<textarea rows={4} dir="ltr" value={edit.message_en} onChange={(e) => setEdit({ ...edit, message_en: e.target.value })} /></label>
          </div>
          <label className="check"><input type="checkbox" checked={edit.via_bot !== false} onChange={(e) => setEdit({ ...edit, via_bot: e.target.checked })} /> إرسال رسالة في البوت (إضافة لإشعار داخل التطبيق)</label>
          <label className="check"><input type="checkbox" checked={edit.enabled} onChange={(e) => setEdit({ ...edit, enabled: e.target.checked })} /> مفعّلة</label>
          <div className="row-gap"><button className="primary">حفظ</button><button type="button" onClick={() => setEdit(null)}>إلغاء</button></div>
        </form>
      )}
      <div className="scrollx">
        <table className="list keep">
          <thead><tr><th>القاعدة</th><th>عندما</th><th>بعد</th><th>العرض</th><th>الحالة</th><th /></tr></thead>
          <tbody>
            {d.rows.map((r) => (
              <tr key={r.id}>
                <td><b>{r.name}</b></td>
                <td>{d.triggers[r.trigger] || r.trigger}</td>
                <td className="mono">{r.delay_hours >= 24 ? `${+(r.delay_hours / 24).toFixed(1)} يوم` : `${r.delay_hours} س`}</td>
                <td>{r.offer_type === "discount" ? `خصم ${r.offer_value}%` : r.offer_type === "free_days" ? `${r.offer_value} يوم` : "—"}</td>
                <td><span className={`badge ${r.enabled ? "approved" : "neutral"}`}>{r.enabled ? "تعمل" : "موقوفة"}</span></td>
                <td className="row-gap">
                  {canWrite && <button onClick={() => toggle(r)}>{r.enabled ? "إيقاف" : "تفعيل"}</button>}
                  {canWrite && <button onClick={() => setEdit({ ...r })}>تعديل</button>}
                  {canWrite && !["winback_linked", "winback_expired"].includes(r.id) && (
                    <button className="danger-ghost" onClick={async () => window.confirm("حذف القاعدة؟") && (await run(() => api.deleteAutomation(r.id), "حُذفت")) && load()}>حذف</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="panel">
        <h2>آخر الإرسالات</h2>
        {d.log.length === 0 && <p className="muted">لم تُرسل أي رسالة تلقائية بعد.</p>}
        {d.log.slice(0, 30).map((l, i) => (
          <div className="kv" key={i}><span>{names[l.rule] || l.rule} ← <span className="mono">{l.uid}</span>{l.reward_id ? " · 🎁" : ""}</span><b className="muted">{when(l.at)}</b></div>
        ))}
      </div>
    </>
  );
}
