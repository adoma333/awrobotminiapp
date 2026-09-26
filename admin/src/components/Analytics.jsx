import React, { useEffect, useState } from "react";
import { api } from "../api";

const n = (v) => (v == null ? "—" : Number(v).toLocaleString("en-US"));
const dur = (s) => (!s ? "0ث" : s < 60 ? `${Math.round(s)}ث` : `${Math.floor(s / 60)}د ${Math.round(s % 60)}ث`);
const ms = (v) => (v == null ? "—" : v >= 1000 ? `${(v / 1000).toFixed(2)}s` : `${Math.round(v)}ms`);
const when = (ts) => (ts ? new Date(ts * 1000).toLocaleString("ar-u-nu-latn", { dateStyle: "short", timeStyle: "short" }) : "—");
const SRC = { direct: "مباشر", campaign: "حملة إعلانية", referral: "إحالة صديق", gift: "رابط هدية", start_param: "رابط بمعامل" };
const EVT = { link_account: "ربط حساب", checkout_open: "فتح الدفع", purchase: "شراء", support_open: "فتح الدعم", register: "تسجيل", share: "مشاركة" };
const PIXELS = [
  ["meta_pixel", "Meta (Facebook / Instagram) Pixel ID", "123456789012345"],
  ["tiktok_pixel", "TikTok Pixel ID", "C1234ABCD5678EFGH"],
  ["ga4_id", "Google Analytics 4 — Measurement ID", "G-XXXXXXXXXX"],
  ["x_pixel", "X (Twitter) Pixel ID", "o1abc"],
  ["snap_pixel", "Snapchat Pixel ID", "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"],
];

function Kpi({ label, value, hint, tone }) {
  return (
    <div className={`kpi ${tone || ""}`}>
      <span className="kpi-label">{label}</span>
      <b className="kpi-value mono">{value}</b>
      {hint && <span className="kpi-hint">{hint}</span>}
    </div>
  );
}

function Bars({ rows, field, color }) {
  const max = Math.max(1, ...rows.map((r) => r[field]));
  return (
    <div className="bars" role="img">
      {rows.map((r) => (
        <div key={r.day} className="bar-col" title={`${r.day}: ${n(r[field])}`}>
          <span style={{ height: `${(r[field] / max) * 100}%`, background: color }} />
        </div>
      ))}
    </div>
  );
}

function Top({ title, rows, label = (k) => k }) {
  const total = rows.reduce((a, r) => a + r.n, 0) || 1;
  return (
    <div className="panel an-top">
      <h3>{title}</h3>
      {rows.length === 0 ? <p className="muted">لا بيانات بعد.</p> : rows.map((r) => (
        <div key={r.k} className="an-row">
          <span>{label(r.k)}</span>
          <b className="mono">{n(r.n)}</b>
          <i style={{ width: `${(r.n / total) * 100}%` }} />
        </div>
      ))}
    </div>
  );
}

/** التحليلات: كل زائر، كل جلسة، كل صفحة — لحظيًا، مع الاحتفاظ والمصادر والأداء ورحلة كل مستخدم. */
export default function Analytics({ canWrite }) {
  const [days, setDays] = useState(30);
  const [d, setD] = useState(null);
  const [err, setErr] = useState("");
  const [tab, setTab] = useState("overview");
  useEffect(() => {
    let alive = true;
    const load = () => api.analytics(days).then((r) => alive && setD(r)).catch(() => alive && setErr("تعذّر تحميل التحليلات."));
    load();
    const id = setInterval(load, 15000); // المتواجدون الآن يتحدثون تلقائيًا
    return () => { alive = false; clearInterval(id); };
  }, [days]);

  return (
    <>
      <div className="topbar">
        <h1>التحليلات وتتبّع الزوار</h1>
        <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
          {[1, 7, 30, 90].map((v) => <option key={v} value={v}>{v === 1 ? "اليوم" : `آخر ${v} يومًا`}</option>)}
        </select>
      </div>
      <div className="tabs page-tabs">
        {[["overview", "نظرة عامة"], ["sources", "المصادر والأجهزة"], ["behavior", "السلوك والصفحات"], ["retention", "الاحتفاظ"], ["perf", "الأداء"], ["journey", "رحلة مستخدم"], ["pixels", "المنصات والبكسلات"]].map(([k, l]) => (
          <button key={k} className={`tab ${tab === k ? "active" : ""}`} onClick={() => setTab(k)}>{l}</button>
        ))}
      </div>
      {err && !d && <p className="error-text">{err}</p>}
      {!d && !err && <p className="muted">…جارٍ التحميل</p>}
      {d && tab === "overview" && <Overview d={d} />}
      {d && tab === "sources" && (
        <div className="an-grid">
          <Top title="المصادر" rows={d.sources} label={(k) => SRC[k] || k} />
          <Top title="الحملات" rows={d.campaigns} />
          <Top title="منصة تلجرام" rows={d.platforms} />
          <Top title="نظام التشغيل" rows={d.os} />
          <Top title="نوع الجهاز" rows={d.device_types} label={(k) => ({ mobile: "جوال", tablet: "تابلت", desktop: "كمبيوتر" }[k] || k)} />
          <Top title="المتصفح" rows={d.browsers} />
          <Top title="اللغة" rows={d.langs} label={(k) => ({ ar: "العربية", en: "English" }[k] || k)} />
          <Top title="المظهر المستخدم" rows={d.themes} label={(k) => ({ dark: "ليلي", light: "نهاري" }[k] || k)} />
        </div>
      )}
      {d && tab === "behavior" && (
        <div className="an-grid">
          <Top title="أكثر الصفحات مشاهدة" rows={d.top_pages} />
          <Top title="صفحات الدخول" rows={d.entry_pages} />
          <Top title="صفحات الخروج" rows={d.exit_pages} />
          <Top title="الأحداث" rows={d.top_events} label={(k) => EVT[k] || k} />
        </div>
      )}
      {d && tab === "retention" && <Retention rows={d.retention} />}
      {d && tab === "perf" && <Perf d={d} />}
      {tab === "journey" && <Journey />}
      {tab === "pixels" && <Pixels canWrite={canWrite} />}
    </>
  );
}

function Overview({ d }) {
  const t = d.totals;
  const c = d.conversions || {};
  const pct = (a, b) => (b ? `${((a / b) * 100).toFixed(1)}%` : "—");
  return (
    <>
      <div className="kpi-grid">
        <Kpi label="🟢 متواجدون الآن" value={n(d.live.users)} hint={d.live.pages.map((p) => `${p.k}: ${p.n}`).join(" · ") || "—"} tone="accent" />
        <Kpi label="نشطون اليوم (DAU)" value={n(d.active.dau)} />
        <Kpi label="نشطون هذا الأسبوع (WAU)" value={n(d.active.wau)} />
        <Kpi label="نشطون هذا الشهر (MAU)" value={n(d.active.mau)} hint={`الالتصاق DAU/MAU: ${pct(d.active.dau, d.active.mau)}`} />
      </div>
      <div className="kpi-grid">
        <Kpi label="الزوار" value={n(t.visitors)} hint={`جدد: ${n(t.new)} · كل الزوار: ${n(t.all_time_visitors)}`} />
        <Kpi label="الجلسات" value={n(t.sessions)} hint={`${t.pages_per_session} صفحة/جلسة`} />
        <Kpi label="متوسط مدة الجلسة" value={dur(t.avg_duration_sec)} hint={`الوسيط: ${dur(t.median_duration_sec)}`} />
        <Kpi label="معدل الارتداد" value={`${t.bounce_pct}%`} hint="جلسة بصفحة واحدة وأقل من 10 ثوانٍ" />
      </div>
      <div className="kpi-grid">
        <Kpi label="ربط حساب" value={n(c.link_account)} hint={`من الزوار: ${pct(c.link_account || 0, t.visitors)}`} />
        <Kpi label="فتح صفحة الدفع" value={n(c.checkout_open)} />
        <Kpi label="عمليات شراء" value={n(c.purchase)} hint={`من فتح الدفع: ${pct(c.purchase || 0, c.checkout_open)}`} tone="accent" />
        <Kpi label="فتح مركز الدعم" value={n(c.support_open)} />
      </div>
      <div className="panel">
        <h2>الزوار يوميًا</h2>
        <Bars rows={d.series} field="visitors" color="var(--accent)" />
        <h3>زوار جدد</h3>
        <Bars rows={d.series} field="new" color="var(--ok)" />
        <h3>مشاهدات الصفحات</h3>
        <Bars rows={d.series} field="pageviews" color="#6aa9ff" />
      </div>
    </>
  );
}

function Retention({ rows }) {
  const cell = (v) => (v == null ? <td className="muted">—</td> : <td className="mono" style={{ background: `rgba(31,167,160,${Math.min(0.85, v / 100 + 0.05)})` }}>{v}%</td>);
  return (
    <div className="panel">
      <h2>الاحتفاظ بالمستخدمين (أفواج أسبوعية)</h2>
      <p className="muted">من دخلوا لأول مرة في كل أسبوع: كم منهم عاد بعد يوم، 7 أيام، 30 يومًا.</p>
      <div className="scrollx">
        <table className="list keep">
          <thead><tr><th>أسبوع أول زيارة</th><th>الحجم</th><th>D1</th><th>D7</th><th>D30</th></tr></thead>
          <tbody>{rows.map((r) => <tr key={r.week}><td className="mono">{r.week}</td><td className="mono">{n(r.size)}</td>{cell(r.d1)}{cell(r.d7)}{cell(r.d30)}</tr>)}</tbody>
        </table>
      </div>
    </div>
  );
}

function Perf({ d }) {
  const p = d.perf;
  return (
    <>
      <div className="kpi-grid">
        <Kpi label="أول بايت (TTFB)" value={ms(p.ttfb.p50)} hint={`p75: ${ms(p.ttfb.p75)} · ${n(p.ttfb.n)} قياس`} />
        <Kpi label="أول رسم (FCP)" value={ms(p.fcp.p50)} hint={`p75: ${ms(p.fcp.p75)}`} />
        <Kpi label="أكبر عنصر (LCP)" value={ms(p.lcp.p50)} hint={`p75: ${ms(p.lcp.p75)} · الممتاز < 2.5s`} tone={p.lcp.p75 && p.lcp.p75 > 4000 ? "bad" : ""} />
        <Kpi label="التحميل الكامل" value={ms(p.load.p50)} hint={`p75: ${ms(p.load.p75)}`} />
      </div>
      <div className="panel">
        <h2>زمن استجابة الخادم لكل مسار</h2>
        <p className="muted">منذ آخر إعادة تشغيل للخدمة — مرتبة حسب عدد الطلبات.</p>
        <div className="scrollx">
          <table className="list keep">
            <thead><tr><th>المسار</th><th>الطلبات</th><th>p50</th><th>p95</th><th>أخطاء</th><th>أخطاء خادم</th></tr></thead>
            <tbody>
              {d.api.map((r) => (
                <tr key={r.route}>
                  <td className="mono" dir="ltr">{r.route}</td>
                  <td className="mono">{n(r.count)}</td>
                  <td className="mono">{ms(r.p50)}</td>
                  <td className="mono" style={{ color: r.p95 > 1500 ? "var(--bad)" : undefined }}>{ms(r.p95)}</td>
                  <td className="mono">{r.errors_pct}%</td>
                  <td className="mono" style={{ color: r.server_errors ? "var(--bad)" : undefined }}>{n(r.server_errors)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}

function Journey() {
  const [uid, setUid] = useState("");
  const [d, setD] = useState(null);
  const [msg, setMsg] = useState("");
  async function load(e) {
    e?.preventDefault();
    if (!/^\d{3,16}$/.test(uid.trim())) return setMsg("أدخل Telegram ID صحيحًا");
    setMsg("");
    try { setD(await api.analyticsUser(uid.trim())); } catch { setMsg("تعذّر التحميل"); }
  }
  const v = d?.visitor;
  return (
    <>
      <form className="filters" onSubmit={load}>
        <input className="search mono" placeholder="Telegram ID للمستخدم" value={uid} onChange={(e) => setUid(e.target.value)} />
        <button className="primary" type="submit">عرض الرحلة</button>
      </form>
      {msg && <p className="error-text">{msg}</p>}
      {d && !v && <div className="empty">لا بيانات تتبّع لهذا المستخدم بعد.</div>}
      {v && (
        <>
          <div className="kpi-grid">
            <Kpi label="أول زيارة" value={when(v.first_seen)} hint={`المصدر: ${SRC[v.first_source?.src] || v.first_source?.src || "—"}${v.first_source?.campaign ? ` · ${v.first_source.campaign}` : ""}`} />
            <Kpi label="آخر ظهور" value={when(v.last_seen)} />
            <Kpi label="الجلسات" value={n(v.sessions)} hint={`أيام النشاط: ${n((v.days || []).length)}`} />
            <Kpi label="الجهاز" value={`${v.device?.os || "—"}`} hint={`${v.device?.platform || ""} · ${v.device?.screen || ""} · ${v.lang || ""}`} />
          </div>
          <div className="panel">
            <h2>الخط الزمني</h2>
            <div className="audit-list">
              {d.events.map((e, i) => (
                <div key={i} className="audit">
                  <div className="audit-top">
                    <b>{e.type === "page_view" ? `📄 ${e.page}` : e.type === "event" ? `⚡ ${EVT[e.name] || e.name}` : e.type === "session_start" ? "▶️ بداية جلسة" : e.type === "session_end" ? "⏹ نهاية جلسة" : `⏱ أداء`}</b>
                    <span className="muted mono">{when(e.at)}</span>
                  </div>
                  {e.props && Object.keys(e.props).length > 0 && <span className="muted mono">{JSON.stringify(e.props)}</span>}
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </>
  );
}

function Pixels({ canWrite }) {
  const [c, setC] = useState(null);
  const [msg, setMsg] = useState("");
  useEffect(() => { api.analyticsConfig().then(setC).catch(() => setMsg("تعذّر التحميل")); }, []);
  if (!c) return <p className="muted">{msg || "جارٍ التحميل…"}</p>;
  async function save() {
    setMsg("");
    try {
      const patch = { enabled: c.enabled, retention_days: Number(c.retention_days) || 90, ...Object.fromEntries(PIXELS.map(([k]) => [k, (c[k] || "").trim()])) };
      setC(await api.saveAnalyticsConfig(patch));
      setMsg("✓ تم الحفظ — تُحمَّل البكسلات في التطبيق عند الفتح التالي");
    } catch (e) { setMsg(`✗ ${e.detail || "فشل الحفظ"}`); }
  }
  return (
    <div className="panel">
      <h2>التكامل مع منصات الإعلان والتحليل</h2>
      <p className="muted">ضع معرّف البكسل فقط (عام بطبيعته). يُرسل التطبيق تلقائيًا: مشاهدة صفحة، تسجيل/ربط حساب، بدء الدفع، الشراء (مع القيمة بالدولار)، التواصل مع الدعم، المشاركة — لقياس الحملات وبناء جماهير إعادة الاستهداف.</p>
      <label className="check"><input type="checkbox" checked={!!c.enabled} onChange={(e) => setC({ ...c, enabled: e.target.checked })} disabled={!canWrite} />تشغيل التتبّع والتحليلات</label>
      <div className="grid-form">
        {PIXELS.map(([k, label, ph]) => (
          <label key={k}>{label}<input className="mono" dir="ltr" placeholder={ph} value={c[k] || ""} onChange={(e) => setC({ ...c, [k]: e.target.value })} disabled={!canWrite} /></label>
        ))}
        <label>مدة الاحتفاظ بالأحداث التفصيلية (يوم)<input type="number" min="7" max="730" value={c.retention_days} onChange={(e) => setC({ ...c, retention_days: e.target.value })} disabled={!canWrite} /></label>
      </div>
      {canWrite && <div className="row-gap"><button className="primary" onClick={save}>حفظ</button></div>}
      {msg && <p className={msg.startsWith("✗") ? "error-text" : "muted"}>{msg}</p>}
    </div>
  );
}
