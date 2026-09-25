import React, { useEffect, useState } from "react";
import { api } from "../api";

const ACTION = { set_wallet: "تغيير محفظة الاستلام", set_window: "تعديل مهلة الدفع", toggle: "تشغيل/إيقاف الدفع بـ TON", transfer: "تحويل TON", gw_payout: "تغيير عنوان استلام بوابة الدفع" };
const EVENT = { otp_requested: "طلب رمز", otp_wrong: "رمز خاطئ", otp_expired: "رمز منتهٍ/مستنفد", otp_invalid: "رمز غير صالح", executed: "نُفّذت", transfer_signed: "وُقّع التحويل", transfer_failed: "فشل التحويل" };
const when = (ts) => (ts ? new Date(ts * 1000).toLocaleString("ar-u-nu-latn", { dateStyle: "short", timeStyle: "short" }) : "—");
const short = (a) => (a ? `${a.slice(0, 6)}…${a.slice(-6)}` : "—");

// TON Connect يُحمَّل عند أول تحويل فقط؛ التوقيع يتم في محفظة الأدمن (الخادم لا يملك المفتاح الخاص)
let uiPromise = null;
function tonUI() {
  if (!uiPromise) {
    uiPromise = import("@tonconnect/ui").then(({ TonConnectUI, THEME }) =>
      new TonConnectUI({ manifestUrl: `${window.location.origin}/api/tonconnect-manifest.json`, uiPreferences: { theme: THEME.DARK } }));
  }
  return uiPromise;
}
async function signTransfer(tx) {
  const ui = await tonUI();
  if (!ui.connected) {
    await new Promise((resolve, reject) => {
      const off = ui.onStatusChange((w) => { if (w) { off(); offM(); resolve(); } });
      const offM = ui.onModalStateChange((s) => { if (s.status === "closed" && !ui.connected) { off(); offM(); reject(new Error("cancelled")); } });
      ui.openModal();
    });
  }
  try {
    return await ui.sendTransaction(tx);
  } finally {
    try { await ui.disconnect(); } catch { /* انتهت الجلسة */ }
  }
}

export default function TonWallet({ canWrite }) {
  const [d, setD] = useState(null);
  const [log, setLog] = useState([]);
  const [err, setErr] = useState("");
  const [otp, setOtp] = useState(null); // {otp_id, action, params}
  const [form, setForm] = useState({ address: "", seconds: 7200, to: "", amount_ton: "", comment: "" });
  const load = () => {
    api.tonOverview().then((r) => { setD(r); setForm((f) => ({ ...f, seconds: r.window_sec })); }).catch((e) => setErr(e.detail || "تعذّر التحميل"));
    api.tonLog().then((r) => setLog(r.rows)).catch(() => {});
  };
  useEffect(load, []);

  async function start(action, params) {
    setErr("");
    try {
      const r = await api.tonOtp(action, params);
      setOtp({ ...r, action, params });
      api.tonLog().then((x) => setLog(x.rows));
    } catch (e) { setErr(e.detail || "تعذّر طلب الرمز"); }
  }

  if (!d) return <p className="muted">{err || "جارٍ التحميل…"}</p>;
  return (
    <>
      <div className="topbar"><h1>محفظة TON</h1><button onClick={load}>تحديث</button></div>
      <div className="kpi-grid">
        <div className="kpi accent"><span className="kpi-label">الرصيد</span><span className="kpi-value">{d.balance_ton ?? "—"} TON</span><span className="kpi-hint">{d.balance_usd != null ? `≈ $${d.balance_usd.toLocaleString("en")}` : "—"}</span></div>
        <div className="kpi"><span className="kpi-label">سعر TON الآن</span><span className="kpi-value">{d.rate_usd ? `$${d.rate_usd}` : "—"}</span></div>
        <div className="kpi"><span className="kpi-label">مهلة انتظار الدفع</span><span className="kpi-value">{Math.round(d.window_sec / 60)} د</span></div>
        <div className={`kpi ${d.enabled ? "ok" : "bad"}`}><span className="kpi-label">الدفع بـ TON</span><span className="kpi-value">{d.enabled ? "مفعّل" : "موقوف"}</span></div>
      </div>
      <div className="panel">
        <h2>محفظة الاستلام</h2>
        {d.configured ? <p className="mono break">{d.wallet}</p> : <p className="error-text">لا توجد محفظة مضبوطة — لن يظهر الدفع بـ TON.</p>}
        <p className="muted">المصدر: {d.source === "admin" ? `لوحة التحكم (آخر تغيير بواسطة ${d.updated_by} · ${when(d.updated_at)})` : "ملف .env"}</p>
        {d.error && <p className="error-text">تعذّر قراءة المعاملات: {d.error}</p>}
      </div>

      {canWrite && (
        <div className="two-col">
          <div className="panel">
            <h2>إعدادات المحفظة <span className="badge pending">OTP</span></h2>
            <p className="muted">كل عملية هنا تتطلب رمز تحقق يُرسل لحسابك في تلجرام عبر بوت الأدمن، ولا تُنفّذ إلا بعد إدخاله.</p>
            <label className="stack">ربط محفظة استلام جديدة<input className="mono" dir="ltr" placeholder="UQ… / EQ…" value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value.trim() })} /></label>
            <div><button disabled={!form.address} onClick={() => start("set_wallet", { address: form.address })}>تغيير المحفظة</button></div>
            <label className="stack">مهلة انتظار الدفع (دقيقة)<input type="number" min="10" max="1440" value={Math.round(form.seconds / 60)} onChange={(e) => setForm({ ...form, seconds: Number(e.target.value) * 60 })} /></label>
            <div><button onClick={() => start("set_window", { seconds: form.seconds })}>حفظ المهلة</button></div>
            <div><button className={d.enabled ? "danger-ghost" : "ok-ghost"} onClick={() => start("toggle", { enabled: !d.enabled })}>{d.enabled ? "إيقاف الدفع بـ TON" : "تشغيل الدفع بـ TON"}</button></div>
          </div>
          <div className="panel">
            <h2>تحويل / سحب <span className="badge pending">OTP</span></h2>
            <p className="muted">الخادم لا يحتفظ بالمفتاح الخاص للمحفظة إطلاقًا. بعد التحقق بالرمز يُفتح TON Connect لتوقّع التحويل من محفظة المشروع على جهازك.</p>
            <label className="stack">إلى العنوان<input className="mono" dir="ltr" placeholder="UQ…" value={form.to} onChange={(e) => setForm({ ...form, to: e.target.value.trim() })} /></label>
            <label className="stack">المبلغ (TON)<input type="number" min="0" step="0.01" value={form.amount_ton} onChange={(e) => setForm({ ...form, amount_ton: e.target.value })} /></label>
            <label className="stack">تعليق (اختياري)<input maxLength={100} value={form.comment} onChange={(e) => setForm({ ...form, comment: e.target.value })} /></label>
            <div><button className="primary" disabled={!form.to || !(Number(form.amount_ton) > 0)} onClick={() => start("transfer", { to: form.to, amount_ton: Number(form.amount_ton), comment: form.comment })}>متابعة التحويل</button></div>
          </div>
        </div>
      )}
      {err && <p className="error-text">{err}</p>}

      <div className="panel">
        <h2>آخر التحويلات الواردة</h2>
        {d.incoming.length === 0 ? <p className="muted">لا توجد تحويلات واردة.</p> : (
          <div className="scrollx">
            <table className="list keep">
              <thead><tr><th>الوقت</th><th>من</th><th>المبلغ</th><th>التعليق / الطلب</th></tr></thead>
              <tbody>
                {d.incoming.map((t) => (
                  <tr key={t.hash}>
                    <td className="mono">{when(t.utime)}</td>
                    <td className="mono">{short(t.source)}</td>
                    <td className="mono">{t.ton} TON</td>
                    <td>{t.order ? <span className="badge approved">{t.order}</span> : <span className="muted">{t.comment || "—"}</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="panel">
        <h2>سجل العمليات الحساسة</h2>
        {log.length === 0 ? <p className="muted">لا توجد محاولات بعد.</p> : (
          <div className="scrollx">
            <table className="list keep">
              <thead><tr><th>الوقت</th><th>العملية</th><th>الحدث</th><th>المنفّذ</th><th>التفاصيل</th></tr></thead>
              <tbody>
                {log.map((r) => (
                  <tr key={r.id}>
                    <td className="mono">{when(r.at)}</td>
                    <td>{r.label}</td>
                    <td><span className={`badge ${r.ok ? "approved" : "rejected"}`}>{EVENT[r.event] || r.event}</span></td>
                    <td className="mono">{r.admin_id}</td>
                    <td className="mono muted">{JSON.stringify(r.detail?.params || {})}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {otp && <OtpModal otp={otp} onClose={() => { setOtp(null); load(); }} />}
    </>
  );
}

function OtpModal({ otp, onClose }) {
  const [code, setCode] = useState("");
  const [state, setState] = useState({ busy: false, msg: "", done: false });
  async function confirm() {
    setState({ busy: true, msg: "" });
    try {
      const r = await api.tonExecute(otp.otp_id, code);
      if (otp.action !== "transfer") return setState({ busy: false, msg: "✓ نُفّذت العملية وسُجّلت", done: true });
      setState({ busy: true, msg: "افتح محفظتك ووقّع التحويل…" });
      try {
        const res = await signTransfer(r.transaction);
        await api.tonTransferResult({ otp_id: otp.otp_id, ok: true, boc: res?.boc || "" });
        setState({ busy: false, msg: "✓ وُقّع التحويل وأُرسل للشبكة", done: true });
      } catch (e) {
        await api.tonTransferResult({ otp_id: otp.otp_id, ok: false, error: String(e?.message || e) }).catch(() => {});
        setState({ busy: false, msg: `✗ لم يُوقّع التحويل: ${e?.message || e}`, done: true });
      }
    } catch (e) {
      const map = { otp_wrong: "الرمز غير صحيح", otp_expired: "انتهت صلاحية الرمز أو استُنفدت المحاولات", otp_invalid: "طلب غير صالح" };
      setState({ busy: false, msg: `✗ ${map[e.detail] || e.detail || "فشل التحقق"}` });
    }
  }
  return (
    <>
      <div className="overlay" onClick={onClose} />
      <div className="otp-modal" role="dialog" aria-modal="true">
        <h2>تأكيد: {ACTION[otp.action]}</h2>
        <p className="muted">{otp.sent ? "أرسلنا رمزًا من 6 أرقام إلى حسابك في تلجرام (صالح 5 دقائق)." : "تعذّر إرسال الرمز عبر البوت — تأكد أنك بدأت محادثة مع بوت الأدمن."}</p>
        <div className="kv"><span>التفاصيل</span><b className="break">{Object.entries(otp.params).map(([k, v]) => `${k}: ${v}`).join(" · ")}</b></div>
        {!state.done && <input className="mono otp-input" inputMode="numeric" maxLength={6} placeholder="000000" value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} autoFocus />}
        {state.msg && <p className={state.msg.startsWith("✗") ? "error-text" : "muted"}>{state.msg}</p>}
        <div className="row-gap">
          {!state.done && <button className="primary" disabled={state.busy || code.length !== 6} onClick={confirm}>تأكيد</button>}
          <button onClick={onClose}>{state.done ? "إغلاق" : "إلغاء"}</button>
        </div>
      </div>
    </>
  );
}
