import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api";

const when = (ts) => (ts ? new Date(ts * 1000).toLocaleString("ar-u-nu-latn", { dateStyle: "short", timeStyle: "short" }) : "—");
const short = (a) => (a ? `${a.slice(0, 8)}…${a.slice(-6)}` : "—");
const NET = { tron: "TRON", bsc: "BNB Smart Chain", ton: "TON" };
const STATUS = {
  waiting: ["بانتظار الدفع", "pending"], partially_paid: ["دفعة ناقصة", "pending"], expired: ["انتهت المهلة (قبول متأخر)", "neutral"],
  finished: ["مكتملة", "approved"], underpaid: ["ناقصة — قرارك", "rejected"], closed: ["أُغلقت بلا دفع", "neutral"],
  replaced: ["استُبدلت", "neutral"], cancelled: ["ملغاة", "neutral"],
};
const OP = { claim: "حجز", funding: "تمويل الغاز", sweeping: "جارٍ التجميع" };
const EXPLORER = {
  tron: (tx) => `https://tronscan.org/#/transaction/${tx}`, bsc: (tx) => `https://bscscan.com/tx/${tx}`,
  ton: (tx) => `https://tonviewer.com/transaction/${tx}`,
};
const TABS = [["overview", "نظرة عامة"], ["invoices", "الفواتير"], ["addresses", "عناوين الإيداع"], ["sweeps", "سجل التجميع"], ["ton", "تحويلات TON"], ["settings", "الإعدادات"], ["payout", "عناوين الاستلام"]];

function copy(v) {
  navigator.clipboard?.writeText(String(v)).catch(() => {});
}

function Msg({ m }) {
  return m ? <p className={m.startsWith("✗") ? "error-text" : "muted"}>{m}</p> : null;
}

/** بوابة الدفع الخاصة AW Pay: تحكم كامل بالعملات والشبكات والفواتير والتجميع وعناوين الاستلام. */
export default function PaymentGateway({ canWrite }) {
  const [tab, setTab] = useState("overview");
  const [d, setD] = useState(null);
  const [err, setErr] = useState("");
  const load = useCallback(() => api.gateway().then(setD).catch((e) => setErr(e.detail || "تعذّر التحميل")), []);
  useEffect(() => { load(); }, [load]);
  if (!d) return <p className="muted">{err || "جارٍ التحميل…"}</p>;
  return (
    <>
      <div className="topbar">
        <h1>بوابة الدفع</h1>
        <div className="row-gap">
          <span className={`badge ${d.active ? "approved" : "neutral"}`}>{d.active ? "تعمل" : "موقوفة — الدفع عبر NOWPayments"}</span>
          <button onClick={load}>تحديث</button>
        </div>
      </div>
      <div className="tabs page-tabs">
        {TABS.map(([k, l]) => <button key={k} className={`tab ${tab === k ? "active" : ""}`} onClick={() => setTab(k)}>{l}</button>)}
      </div>
      {tab === "overview" && <Overview d={d} canWrite={canWrite} reload={load} />}
      {tab === "invoices" && <Invoices canWrite={canWrite} />}
      {tab === "addresses" && <Addresses canWrite={canWrite} />}
      {tab === "sweeps" && <Sweeps />}
      {tab === "ton" && <TonIncoming />}
      {tab === "settings" && <Settings d={d} canWrite={canWrite} onSaved={setD} />}
      {tab === "payout" && <Payout d={d} canWrite={canWrite} reload={load} />}
    </>
  );
}

// ───────────── نظرة عامة ─────────────
function Overview({ d, canWrite, reload }) {
  const [m, setM] = useState("");
  const s = d.stats;
  async function toggle() {
    setM("");
    try { await api.saveGateway({ enabled: !d.config.enabled }); reload(); } catch (e) { setM(`✗ ${e.detail === "gateway_master_key_missing" ? "أضف GATEWAY_MASTER_KEY في .env أولًا" : e.detail || "فشل"}`); }
  }
  return (
    <>
      <div className="kpi-grid">
        <div className="kpi accent"><span className="kpi-label">إيرادات 30 يومًا</span><span className="kpi-value mono">${s.revenue_usd_30d}</span><span className="kpi-hint">{s.finished_30d} دفعة مكتملة</span></div>
        <div className="kpi"><span className="kpi-label">فواتير مفتوحة</span><span className="kpi-value mono">{s.open}</span></div>
        <div className="kpi"><span className="kpi-label">دفعات ناقصة جارية</span><span className="kpi-value mono">{s.partial}</span></div>
        <div className={`kpi ${s.underpaid ? "bad" : ""}`}><span className="kpi-label">تحتاج قرارك</span><span className="kpi-value mono">{s.underpaid}</span></div>
      </div>

      <div className="panel">
        <h2>الحالة</h2>
        <div className="kv"><span>المفتاح الرئيسي (GATEWAY_MASTER_KEY في .env)</span><b>{d.master_key ? "✅ مضبوط" : "❌ غير مضبوط"}</b></div>
        {Object.entries(NET).map(([k, l]) => (
          <div className="kv" key={k}><span>{l}</span><b>{d.ready[k] ? "✅ جاهزة" : d.config.payout[k] ? "❌ تحتاج المفتاح الرئيسي" : "⚠️ أضف عنوان الاستلام"}</b></div>
        ))}
        {canWrite && (
          <div className="row-gap">
            <button className={d.config.enabled ? "danger-ghost" : "primary"} onClick={toggle}>{d.config.enabled ? "إيقاف البوابة (الرجوع لـ NOWPayments)" : "تشغيل البوابة الخاصة"}</button>
          </div>
        )}
        <Msg m={m} />
        <p className="muted">
          TRON و BSC: لكل مستخدم عنوان إيداع خاص يُشتق من المفتاح الرئيسي، ويُجمَّع رصيده تلقائيًا لعنوانك عند بلوغ الحد الأدنى.
          TON: يدفع المستخدم مباشرة لعنوانك مع تعليق فريد لكل فاتورة، فلا تجميع ولا رسوم.
        </p>
      </div>

      <div className="panel">
        <h2>خزان الغاز (رسوم التجميع)</h2>
        <p className="muted">اشحن هذين العنوانين بمبلغ صغير: التجميع يدفع منهما رسوم تحويل USDT من عناوين الإيداع (TRON: نحو 15–30 TRX للتحويل الواحد · BSC: أقل من 0.001 BNB).</p>
        {Object.keys(d.gas || {}).length === 0 && <p className="error-text">يظهر بعد ضبط المفتاح الرئيسي.</p>}
        {Object.entries(d.gas || {}).map(([k, g]) => (
          <div className="kv" key={k}>
            <span>{NET[k]} · <code className="mono" dir="ltr">{g.address}</code> <button className="chip" onClick={() => copy(g.address)}>نسخ</button></span>
            <b className={g.low ? "error-text" : ""} dir="auto">{g.error ? `تعذّر القراءة (${g.error})` : `${g.balance} ${g.symbol}${g.low ? " ⚠️ منخفض" : ""}`}</b>
          </div>
        ))}
      </div>
    </>
  );
}

// ───────────── الفواتير ─────────────
function Invoices({ canWrite }) {
  const [rows, setRows] = useState(null);
  const [status, setStatus] = useState("");
  const [m, setM] = useState("");
  const load = useCallback(() => api.gatewayInvoices(status).then((r) => setRows(r.rows)).catch(() => setRows([])), [status]);
  useEffect(() => { load(); }, [load]);
  async function act(fn, ok) {
    setM("");
    try { await fn(); setM(`✓ ${ok}`); load(); } catch (e) { setM(`✗ ${e.detail || "فشلت العملية"}`); }
  }
  return (
    <>
      <div className="filters">
        <select value={status} onChange={(e) => setStatus(e.target.value)} style={{ width: "auto" }}>
          <option value="">كل الحالات</option>
          {Object.entries(STATUS).map(([k, [l]]) => <option key={k} value={k}>{l}</option>)}
        </select>
      </div>
      <Msg m={m} />
      {rows && rows.length === 0 && <div className="empty">لا فواتير.</div>}
      {rows && rows.length > 0 && (
        <div className="scrollx">
          <table className="list keep">
            <thead><tr><th>الفاتورة</th><th>المستخدم</th><th>المطلوب</th><th>المستلم</th><th>الحالة</th><th>أُنشئت</th><th /></tr></thead>
            <tbody>
              {rows.map((r) => {
                const [l, cls] = STATUS[r.status] || [r.status, "neutral"];
                return (
                  <tr key={r.id}>
                    <td><bdi className="mono" dir="ltr">{r.id}</bdi><div className="muted">{NET[r.network]}{r.memo ? ` · تعليق ${r.memo}` : ""}</div></td>
                    <td className="mono">{r.uid}</td>
                    <td className="mono"><bdi dir="ltr">{r.amount} {r.symbol}</bdi><div className="muted">${r.amount_usd}</div></td>
                    <td className="mono"><bdi dir="ltr">{r.received} {r.symbol}</bdi></td>
                    <td>
                      <span className={`badge ${cls}`}>{l}</span>
                      {r.manual_accept && <div className="muted">قبول يدوي: {r.manual_accept.note || "—"}</div>}
                      {r.check_error && <div className="error-text">{r.check_error}</div>}
                    </td>
                    <td className="muted">{when(r.created_at)}</td>
                    <td className="row-gap">
                      {["waiting", "partially_paid", "expired"].includes(r.status) && <button onClick={() => act(() => api.gatewayCheck(r.id), "تم الفحص")}>فحص الآن</button>}
                      {canWrite && !["finished", "cancelled", "replaced"].includes(r.status) && (
                        <button onClick={() => { const note = window.prompt("قبول الفاتورة وتفعيل الاشتراك يدويًا. سبب القبول:", r.status === "underpaid" ? "قبول دفعة ناقصة" : ""); if (note !== null) act(() => api.gatewayAccept(r.id, note), "فُعّل الاشتراك"); }}>قبول وتفعيل</button>
                      )}
                      {canWrite && ["waiting", "partially_paid", "expired", "underpaid"].includes(r.status) && (
                        <button className="danger-ghost" onClick={() => window.confirm("إلغاء الفاتورة؟") && act(() => api.gatewayCancel(r.id), "أُلغيت")}>إلغاء</button>
                      )}
                      {(r.tx_hashes || []).slice(0, 2).map((h) => <a key={h} className="btn-link" href={EXPLORER[r.network](h)} target="_blank" rel="noreferrer">TX</a>)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

// ───────────── عناوين الإيداع ─────────────
function Addresses({ canWrite }) {
  const [rows, setRows] = useState(null);
  const [m, setM] = useState("");
  const [busy, setBusy] = useState("");
  const load = useCallback(() => api.gatewayAddresses().then((r) => setRows(r.rows)).catch(() => setRows([])), []);
  useEffect(() => { load(); }, [load]);
  async function sweep(r) {
    setBusy(r.id); setM("");
    try {
      const x = await api.gatewaySweep(r.network, r.uid);
      setM(`✓ ${{ funding: "أُرسل الغاز — سيكتمل التجميع تلقائيًا بعد التأكيد", sweeping: "أُرسل التحويل لعنوان الاستلام", idle: "لا رصيد للتجميع", open_invoice: "على العنوان فاتورة مفتوحة — لاحقًا", done: "اكتمل" }[x.state] || x.state}`);
      load();
    } catch (e) { setM(`✗ ${e.detail || "فشل التجميع"}`); } finally { setBusy(""); }
  }
  return (
    <>
      <p className="muted">عنوان لكل مستخدم على كل شبكة. «بحاجة للتجميع» = وصله مال لم يُجمَّع بعد. التجميع التلقائي يعمل كل 3 دقائق حسب الحد الأدنى في الإعدادات.</p>
      <Msg m={m} />
      {rows && rows.length === 0 && <div className="empty">لا عناوين بعد — تُنشأ عند أول فاتورة على TRON أو BSC.</div>}
      {rows && rows.length > 0 && (
        <div className="scrollx">
          <table className="list keep">
            <thead><tr><th>الشبكة</th><th>المستخدم</th><th>العنوان</th><th>آخر أرصدة</th><th>الحالة</th><th /></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td>{NET[r.network]}</td>
                  <td className="mono">{r.uid}</td>
                  <td><code className="mono" dir="ltr" title={r.address}>{short(r.address)}</code> <button className="chip" onClick={() => copy(r.address)}>نسخ</button></td>
                  <td className="mono">{r.balances ? Object.entries(r.balances).map(([k, v]) => <div key={k}>{v} {k.replace(/trc20|bsc/, "").toUpperCase()}</div>) : "—"}{r.balances_at && <div className="muted">{when(r.balances_at)}</div>}</td>
                  <td>
                    {r.op ? <span className="badge pending">{OP[r.op.stage] || r.op.stage}</span> : r.dirty ? <span className="badge pending">بحاجة للتجميع</span> : <span className="badge neutral">هادئ</span>}
                    {r.open_order && <div className="muted">فاتورة مفتوحة</div>}
                    {r.sweep_error && <div className="error-text">{r.sweep_error}</div>}
                  </td>
                  <td>{canWrite && <button disabled={busy === r.id || !!r.open_order} onClick={() => sweep(r)}>{busy === r.id ? "…" : "تجميع الآن"}</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

// ───────────── سجل التجميع ─────────────
function Sweeps() {
  const [rows, setRows] = useState(null);
  useEffect(() => { api.gatewaySweeps().then((r) => setRows(r.rows)).catch(() => setRows([])); }, []);
  if (!rows) return <p className="muted">جارٍ التحميل…</p>;
  if (!rows.length) return <div className="empty">لم تتم أي عملية تجميع بعد.</div>;
  return (
    <div className="scrollx">
      <table className="list keep">
        <thead><tr><th>الوقت</th><th>الشبكة</th><th>المبلغ</th><th>من</th><th>إلى</th><th>المعاملة</th></tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td className="muted">{when(r.at)}</td>
              <td>{NET[r.network]}</td>
              <td className="mono">{r.amount} {String(r.asset).replace(/trc20|bsc/, "").toUpperCase()}</td>
              <td><code className="mono" dir="ltr">{short(r.address)}</code></td>
              <td><code className="mono" dir="ltr">{short(r.to)}</code></td>
              <td><a className="btn-link" href={EXPLORER[r.network](r.tx)} target="_blank" rel="noreferrer">عرض</a></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ───────────── تحويلات TON الواردة ─────────────
function TonIncoming() {
  const [rows, setRows] = useState(null);
  useEffect(() => { api.gatewayTonIncoming().then((r) => setRows(r.rows)).catch(() => setRows([])); }, []);
  if (!rows) return <p className="muted">جارٍ التحميل…</p>;
  return (
    <>
      <p className="muted">آخر التحويلات الواردة لعنوان TON. التحويل «غير مطابق» وصل بلا تعليق صحيح — يمكنك قبول فاتورة صاحبه يدويًا من تبويب الفواتير.</p>
      {!rows.length && <div className="empty">لا تحويلات.</div>}
      {rows.length > 0 && (
        <div className="scrollx">
          <table className="list keep">
            <thead><tr><th>الوقت</th><th>المبلغ</th><th>التعليق</th><th>المُرسِل</th><th>الفاتورة</th><th /></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={`${r.hash}-${r.asset}`}>
                  <td className="muted">{when(r.utime)}</td>
                  <td className="mono">{r.amount_text} {r.asset === "ton" ? "TON" : "USDT"}</td>
                  <td className="mono">{r.comment || "—"}</td>
                  <td><code className="mono" dir="ltr">{short(r.source)}</code></td>
                  <td>{r.order_id ? <span className="badge approved">{r.order_id}</span> : <span className="badge pending">غير مطابق</span>}</td>
                  <td>{r.hash && <a className="btn-link" href={EXPLORER.ton(r.hash)} target="_blank" rel="noreferrer">TX</a>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

// ───────────── الإعدادات ─────────────
function Settings({ d, canWrite, onSaved }) {
  const [c, setC] = useState(d.config);
  const [m, setM] = useState("");
  const set = (patch) => setC({ ...c, ...patch });
  async function save() {
    setM("");
    try { onSaved(await api.saveGateway(c)); setM("✓ تم الحفظ"); } catch (e) { setM(`✗ ${e.detail || "فشل الحفظ"}`); }
  }
  const N = (k, label, min, max, step = 1) => (
    <label>{label}<input className="mono" type="number" min={min} max={max} step={step} value={c[k]} disabled={!canWrite} onChange={(e) => set({ [k]: Number(e.target.value) })} /></label>
  );
  return (
    <>
      <div className="panel">
        <h2>العملات المتاحة للمستخدمين</h2>
        {Object.entries(d.assets).map(([k, a]) => (
          <label className="check" key={k}>
            <input type="checkbox" checked={c.assets[k] !== false} disabled={!canWrite} onChange={(e) => set({ assets: { ...c.assets, [k]: e.target.checked } })} />
            {a.symbol} · {a.label} {!d.ready[a.network] && <span className="muted">(الشبكة غير جاهزة)</span>}
          </label>
        ))}
      </div>
      <div className="panel">
        <h2>الفواتير والتحقق</h2>
        <div className="grid-form">
          {N("window_min", "مهلة الدفع (دقيقة)", 10, 1440)}
          {N("partial_grace_min", "تمديد المهلة عند دفعة ناقصة (دقيقة)", 10, 2880)}
          {N("late_accept_hours", "قبول الدفعات المتأخرة حتى (ساعة)", 0, 720)}
          {N("tolerance_pct", "قبول نقص حتى (%)", 0, 5, 0.1)}
          {N("bsc_confirmations", "تأكيدات BSC المطلوبة (كتلة)", 3, 60)}
        </div>
        <p className="muted">USDT يُطلب بالمبلغ نفسه تمامًا (12 لا 12.000850). TRX و BNB و TON بسعر السوق لحظة إنشاء الفاتورة مقرّبًا لأعلى.</p>
      </div>
      <div className="panel">
        <h2>التجميع التلقائي</h2>
        <label className="check"><input type="checkbox" checked={!!c.auto_sweep} disabled={!canWrite} onChange={(e) => set({ auto_sweep: e.target.checked })} /> تجميع الأرصدة تلقائيًا إلى عناوين الاستلام</label>
        <div className="grid-form">
          <label>الحد الأدنى للتجميع — TRON ($)<input className="mono" type="number" min="0" value={c.sweep_min_usd.tron} disabled={!canWrite} onChange={(e) => set({ sweep_min_usd: { ...c.sweep_min_usd, tron: Number(e.target.value) } })} /></label>
          <label>الحد الأدنى للتجميع — BSC ($)<input className="mono" type="number" min="0" value={c.sweep_min_usd.bsc} disabled={!canWrite} onChange={(e) => set({ sweep_min_usd: { ...c.sweep_min_usd, bsc: Number(e.target.value) } })} /></label>
          {N("tron_fee_limit_trx", "أقصى رسوم لتحويل TRC20 (TRX)", 10, 300)}
          <label>تنبيه خزان الغاز TRON تحت (TRX)<input className="mono" type="number" min="0" value={c.gas_alert.tron} disabled={!canWrite} onChange={(e) => set({ gas_alert: { ...c.gas_alert, tron: Number(e.target.value) } })} /></label>
          <label>تنبيه خزان الغاز BSC تحت (BNB)<input className="mono" type="number" min="0" step="0.001" value={c.gas_alert.bsc} disabled={!canWrite} onChange={(e) => set({ gas_alert: { ...c.gas_alert, bsc: Number(e.target.value) } })} /></label>
        </div>
        <p className="muted">تحويل USDT على TRON مكلف نسبيًا (طاقة الشبكة)، لذلك حدّ أدنى أعلى على TRON يوفّر الرسوم: يُجمَّع رصيد عدة دفعات في تحويل واحد.</p>
      </div>
      {canWrite && <div className="row-gap"><button className="primary" onClick={save}>حفظ الإعدادات</button><Msg m={m} /></div>}
    </>
  );
}

// ───────────── عناوين الاستلام (OTP) ─────────────
function Payout({ d, canWrite, reload }) {
  const [form, setForm] = useState({ network: "tron", address: "" });
  const [otp, setOtp] = useState(null);
  const [code, setCode] = useState("");
  const [m, setM] = useState("");
  async function start() {
    setM("");
    try { setOtp(await api.tonOtp("gw_payout", form)); setCode(""); } catch (e) { setM(`✗ ${e.detail || "عنوان غير صالح لهذه الشبكة"}`); }
  }
  async function confirm() {
    setM("");
    try { await api.tonExecute(otp.otp_id, code); setOtp(null); setForm({ ...form, address: "" }); setM("✓ تم تغيير عنوان الاستلام"); reload(); } catch (e) { setM(`✗ ${{ otp_wrong: "رمز خاطئ", otp_expired: "انتهت صلاحية الرمز" }[e.detail] || e.detail || "فشل"}`); }
  }
  return (
    <>
      <div className="panel">
        <h2>عناوين الاستلام الحالية</h2>
        <p className="muted">إلى هذه العناوين تُجمَّع كل المدفوعات (TRON و BSC) أو تُدفع مباشرة (TON)، كلٌّ بعملته نفسها.</p>
        {Object.entries(NET).map(([k, l]) => (
          <div className="kv" key={k}><span>{l}</span><b className="mono" dir="ltr">{d.config.payout[k] || "—"}</b></div>
        ))}
      </div>
      {canWrite && (
        <div className="panel">
          <h2>تغيير عنوان استلام <span className="badge pending">OTP</span></h2>
          <p className="muted">عملية حساسة: لا تُنفَّذ إلا برمز يصل لحسابك في تلجرام، وتُسجَّل في سجل العمليات. تأكد أن العنوان من محفظة تملك مفاتيحها (لا عنوان منصة يحتاج Memo).</p>
          {!otp ? (
            <>
              <div className="grid-form">
                <label>الشبكة
                  <select value={form.network} onChange={(e) => setForm({ ...form, network: e.target.value })}>
                    {Object.entries(NET).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                  </select>
                </label>
                <label>العنوان الجديد<input className="mono" dir="ltr" placeholder={{ tron: "T…", bsc: "0x…", ton: "UQ… / EQ…" }[form.network]} value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value.trim() })} /></label>
              </div>
              <div><button className="primary" disabled={!form.address} onClick={start}>إرسال رمز التحقق</button></div>
            </>
          ) : (
            <>
              <p>أُرسل رمز من 6 أرقام إلى تلجرام لتغيير عنوان {NET[form.network]} إلى <code className="mono" dir="ltr">{form.address}</code></p>
              <div className="grid-form"><label>الرمز<input className="mono" dir="ltr" inputMode="numeric" maxLength={6} autoFocus value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} /></label></div>
              <div className="row-gap"><button className="primary" disabled={code.length !== 6} onClick={confirm}>تأكيد</button><button onClick={() => setOtp(null)}>إلغاء</button></div>
            </>
          )}
          <Msg m={m} />
        </div>
      )}
    </>
  );
}
