import React, { useCallback, useEffect, useState } from "react";

// ─────────── حالة النظام بأسلوب n8n: كل فرع عقدة حية بأيقونته وحالته وتفاصيله ───────────
const STATUS_META = {
  up: { color: "#3ddc97", label: "يعمل" },
  degraded: { color: "#e5b84b", label: "يحتاج انتباه" },
  idle: { color: "#6aa9ff", label: "خامل (عند الحاجة)" },
  unknown: { color: "#6b6459", label: "بانتظار أول فحص" },
  down: { color: "#ff6b5e", label: "متوقف" },
  not_configured: { color: "#6b6459", label: "غير مُهيّأ" },
};

// أيقونات مرسومة (24×24) بألوان الخدمات
const G = {
  telegram: <><circle cx="12" cy="12" r="11" fill="#29a9eb" /><path d="M5.5 11.6 17 7.2c.5-.2 1 .1.8.9l-2 9.3c-.1.6-.6.8-1.1.5l-3-2.2-1.5 1.4c-.2.2-.4.3-.6.3l.2-3.1 5.6-5.1c.2-.2 0-.3-.3-.1l-7 4.4-3-.9c-.6-.2-.6-.6.1-.9Z" fill="#fff" /></>,
  app: <><rect x="6" y="1.5" width="12" height="21" rx="3" fill="#1b1612" stroke="#ff8a00" strokeWidth="1.5" /><rect x="8" y="4.5" width="8" height="12" rx="1" fill="#ff8a00" opacity=".25" /><path d="M9.5 8.5h5M9.5 11h3" stroke="#ff8a00" strokeWidth="1.3" strokeLinecap="round" /><circle cx="12" cy="19.3" r="1" fill="#ff8a00" /></>,
  api: <><circle cx="12" cy="12" r="11" fill="#059485" /><path d="M13.2 4 7 13.2h4.4L10.6 20l6.4-9.4h-4.5Z" fill="#fff" /></>,
  db: <><ellipse cx="12" cy="5.5" rx="8" ry="3" fill="#0f80cc" /><path d="M4 5.5v13c0 1.7 3.6 3 8 3s8-1.3 8-3v-13c0 1.7-3.6 3-8 3s-8-1.3-8-3Z" fill="#0b6aa8" /><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" fill="none" stroke="#44a8e8" strokeWidth="1.2" /></>,
  scheduler: <><circle cx="12" cy="12" r="10.5" fill="#7c5cff" /><circle cx="12" cy="12" r="7.5" fill="#fff" /><path d="M12 7.5V12l3.2 2" stroke="#7c5cff" strokeWidth="1.8" strokeLinecap="round" fill="none" /></>,
  sync: <><circle cx="12" cy="12" r="11" fill="#1fa7a0" /><path d="M17 9.5A5.5 5.5 0 0 0 7.2 8.3M7 14.5a5.5 5.5 0 0 0 9.8 1.2" stroke="#fff" strokeWidth="1.8" fill="none" strokeLinecap="round" /><path d="M7 5.5v3h3M17 18.5v-3h-3" stroke="#fff" strokeWidth="1.8" fill="none" strokeLinecap="round" strokeLinejoin="round" /></>,
  mt5_bridge: <><rect x="1.5" y="1.5" width="21" height="21" rx="5" fill="#0d3a66" /><path d="M6 17V9M10 17V6M14 17v-5M18 17V8" stroke="#39c1ff" strokeWidth="2" strokeLinecap="round" /><rect x="5" y="10" width="2" height="4" fill="#39c1ff" /><rect x="13" y="12.5" width="2" height="3" fill="#ff6b5e" /></>,
  mt5_robot: <><rect x="3" y="6" width="18" height="13" rx="4" fill="#26303a" stroke="#ff8a00" strokeWidth="1.4" /><circle cx="9" cy="12.5" r="1.6" fill="#3ddc97" /><circle cx="15" cy="12.5" r="1.6" fill="#3ddc97" /><path d="M12 6V3" stroke="#ff8a00" strokeWidth="1.5" /><circle cx="12" cy="2.5" r="1.2" fill="#ff8a00" /><path d="M8 16.3h8" stroke="#ff8a00" strokeWidth="1.3" strokeLinecap="round" /></>,
  gateway: <><path d="M12 1.8 3.5 5v6.2c0 5 3.6 9.2 8.5 11 4.9-1.8 8.5-6 8.5-11V5Z" fill="#ff8a00" /><path d="M8.2 12.2 11 15l5-5.3" stroke="#140700" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" /></>,
  nowpayments: <><rect x="1.5" y="1.5" width="21" height="21" rx="6" fill="#64c69f" /><path d="M7 17V7l10 10V7" stroke="#0b2e22" strokeWidth="2.2" fill="none" strokeLinecap="round" strokeLinejoin="round" /></>,
  ai: <><defs><linearGradient id="gm" x1="0" x2="1" y1="0" y2="1"><stop offset="0" stopColor="#4f8cff" /><stop offset=".55" stopColor="#9b6bff" /><stop offset="1" stopColor="#ff6fa1" /></linearGradient></defs><path d="M12 1.5c.7 5.6 4.9 9.8 10.5 10.5-5.6.7-9.8 4.9-10.5 10.5C11.3 16.9 7.1 12.7 1.5 12 7.1 11.3 11.3 7.1 12 1.5Z" fill="url(#gm)" /></>,
  analytics: <><rect x="1.5" y="1.5" width="21" height="21" rx="5" fill="#f29d38" /><path d="M6.5 17v-4M10.5 17V8M14.5 17v-6M18.5 17V6" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" /></>,
  storage: <><rect x="2.5" y="5" width="19" height="14" rx="3" fill="#48515c" /><rect x="5" y="8" width="10" height="2" rx="1" fill="#aab4bf" /><rect x="5" y="12" width="7" height="2" rx="1" fill="#aab4bf" /><circle cx="18" cy="15.5" r="1.4" fill="#3ddc97" /></>,
  errors: <><path d="M12 2 1.5 21h21Z" fill="#ff6b5e" /><path d="M12 9v5" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" /><circle cx="12" cy="17.3" r="1.3" fill="#fff" /></>,
  n8n: <><rect x="1" y="1" width="22" height="22" rx="6" fill="#ea4b71" /><circle cx="6" cy="12" r="2.2" fill="none" stroke="#fff" strokeWidth="1.6" /><circle cx="12.5" cy="12" r="2.2" fill="none" stroke="#fff" strokeWidth="1.6" /><circle cx="18.5" cy="7.5" r="2.2" fill="none" stroke="#fff" strokeWidth="1.6" /><circle cx="18.5" cy="16.5" r="2.2" fill="none" stroke="#fff" strokeWidth="1.6" /><path d="M8.2 12h2.1M14.6 11l2.1-2.2M14.6 13l2.1 2.2" stroke="#fff" strokeWidth="1.6" /></>,
};

// العقد ومواقعها على اللوحة (1180×660) — الأعمدة: المصادر ← القلب ← المعالجة ← التكاملات
const NODES = {
  telegram: { x: 30, y: 90, label: "Telegram Bot API", sub: "Webhook", svc: "telegram", icon: "telegram" },
  app: { x: 30, y: 300, label: "Mini App", sub: "واجهة المستخدم", svc: "errors", icon: "app" },
  errors: { x: 30, y: 510, label: "أخطاء الأجهزة", sub: "آخر ساعة", svc: "errors", icon: "errors" },
  api: { x: 330, y: 300, label: "AW API · FastAPI", sub: "الخادم الرئيسي", svc: "api", icon: "api" },
  db: { x: 330, y: 90, label: "قاعدة البيانات", sub: "SQLite · WAL", svc: "firestore", icon: "db" },
  storage: { x: 330, y: 510, label: "التخزين والنسخ", sub: "القرص + النسخ الاحتياطي", svc: "storage", icon: "storage" },
  scheduler: { x: 620, y: 40, label: "المهام المجدولة", sub: "APScheduler", svc: "scheduler", icon: "scheduler" },
  sync: { x: 620, y: 175, label: "عامل المزامنة", sub: "aw-sync", svc: "sync", icon: "sync" },
  gateway: { x: 620, y: 320, label: "بوابة AW Pay", sub: "USDT · TON · BSC", svc: "gateway", icon: "gateway" },
  ai: { x: 620, y: 455, label: "Gemini AI", sub: "الدعم الذكي", svc: "ai", icon: "ai" },
  analytics: { x: 620, y: 580, label: "التحليلات", sub: "الزوار والأداء", svc: "analytics", icon: "analytics" },
  mt5_bridge: { x: 910, y: 110, label: "جسر MT5", sub: "Wine · rpyc", svc: "mt5_bridge", icon: "mt5_bridge" },
  mt5_robot: { x: 910, y: 245, label: "ترمنال الروبوت", sub: "Heartbeat", svc: "mt5_robot", icon: "mt5_robot" },
  nowpayments: { x: 910, y: 380, label: "NOWPayments", sub: "بوابة العملات", svc: "nowpayments", icon: "nowpayments" },
  n8n: { x: 910, y: 520, label: "n8n", sub: "الأتمتة", svc: "n8n", icon: "n8n" },
};
const EDGES = [["telegram", "api"], ["app", "api"], ["app", "errors"], ["api", "db"], ["api", "storage"], ["db", "storage"], ["api", "scheduler"],
  ["scheduler", "sync"], ["sync", "mt5_bridge"], ["mt5_bridge", "mt5_robot"], ["api", "gateway"], ["gateway", "nowpayments"], ["api", "ai"],
  ["api", "analytics"], ["api", "n8n"], ["sync", "db"]];
const W = 240;
const H = 76;

const DETAIL_LABEL = {
  uptime_min: "مدة التشغيل (دقيقة)", python: "Python", memory_mb: "الذاكرة (MB)", threads: "الخيوط", pid: "PID", webhook: "Webhook مضبوط",
  pending_updates: "تحديثات معلّقة", max_connections: "أقصى اتصالات", ip: "IP", running: "يعمل", jobs: "المهام", failing: "مهام متعثرة",
  linked_accounts: "حسابات مربوطة", sync_errors: "أخطاء مزامنة", stale_3h: "لم تتحدث منذ 3 ساعات", last_sync_min: "آخر مزامنة (دقيقة)",
  networks: "الشبكات", waiting_invoices: "فواتير بانتظار الدفع", last_scan_sec: "آخر فحص (ثانية)", reconcile_ok: "آخر مطابقة ناجحة",
  last_reconcile_min: "آخر مطابقة (دقيقة)", model: "النموذج", fallbacks: "الاحتياطية", last_ok_min: "آخر نجاح (دقيقة)", calls: "الطلبات",
  failures: "الفشل", disk_free_gb: "مساحة حرة (GB)", disk_free_pct: "مساحة حرة %", last_backup_h: "آخر نسخة احتياطية (ساعة)",
  errors_1h: "أخطاء آخر ساعة", critical_1h: "حرجة", network_1h: "اتصال", live_users: "متواجدون الآن", dau: "نشطون اليوم", sessions_today: "جلسات اليوم",
};

async function fetchStatus() {
  const res = await fetch("/api/system/status", { credentials: "include" });
  if (!res.ok) throw new Error(String(res.status));
  return res.json();
}

function metric(svc) {
  if (!svc) return "";
  if (svc.latency_ms !== undefined) return `${svc.latency_ms}ms`;
  const d = svc.details || {};
  for (const k of ["live_users", "linked_accounts", "waiting_invoices", "errors_1h", "jobs", "disk_free_pct", "uptime_min"]) {
    if (d[k] !== undefined) return `${DETAIL_LABEL[k] || k}: ${d[k]}`;
  }
  return "";
}

export default function SystemStatus() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [sel, setSel] = useState("api");
  const [at, setAt] = useState(0);

  const load = useCallback(() => {
    fetchStatus().then((r) => { setData(r); setError(""); setAt(Date.now()); }).catch(() => setError("تعذّر تحميل حالة النظام."));
  }, []);
  useEffect(() => {
    load();
    const id = setInterval(load, 10000); // تحديث حي كل 10 ثوانٍ
    return () => clearInterval(id);
  }, [load]);

  const svcOf = (key) => {
    const n = NODES[key];
    const s = data?.services?.[n.svc];
    if (key === "app" && data) return { status: "up", details: { errors_1h: s?.details?.errors_1h } };
    return s || { status: "unknown" };
  };
  const overall = STATUS_META[data?.overall] || STATUS_META.unknown;
  const counts = data ? Object.values(data.services).reduce((a, s) => ({ ...a, [s.status]: (a[s.status] || 0) + 1 }), {}) : {};
  const cur = NODES[sel];
  const curSvc = svcOf(sel);

  return (
    <>
      <div className="topbar">
        <h1>حالة النظام</h1>
        <span className="ns-overall" style={{ color: overall.color }}><i style={{ background: overall.color }} />{data ? `الحالة العامة: ${overall.label}` : "…"}</span>
        <span className="muted">{at ? `آخر تحديث ${new Date(at).toLocaleTimeString("en-GB")}` : ""} · تحديث كل 10 ثوانٍ</span>
      </div>
      {error && <p className="error-text">{error}</p>}
      {data && (
        <div className="ns-summary">
          {Object.entries(counts).map(([k, n]) => <span key={k} style={{ borderColor: (STATUS_META[k] || STATUS_META.unknown).color }}><i style={{ background: (STATUS_META[k] || STATUS_META.unknown).color }} />{(STATUS_META[k] || STATUS_META.unknown).label}: <b>{n}</b></span>)}
        </div>
      )}

      <div className="ns-layout">
        <div className="ns-canvas">
          <svg viewBox="0 0 1180 680" role="img" aria-label="مخطط النظام">
            <defs>
              <pattern id="nsdots" width="22" height="22" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r="1" fill="rgba(128,128,128,.25)" /></pattern>
            </defs>
            <rect width="1180" height="680" fill="url(#nsdots)" />
            {EDGES.map(([a, b]) => {
              const A = NODES[a];
              const B = NODES[b];
              const st = svcOf(b).status;
              const c = (STATUS_META[st] || STATUS_META.unknown).color;
              const vertical = Math.abs(A.x - B.x) < 40;
              const x1 = vertical ? A.x + W / 2 : A.x + W;
              const y1 = vertical ? (A.y < B.y ? A.y + H : A.y) : A.y + H / 2;
              const x2 = vertical ? B.x + W / 2 : B.x;
              const y2 = vertical ? (A.y < B.y ? B.y : B.y + H) : B.y + H / 2;
              const d = vertical ? `M${x1},${y1} C${x1},${(y1 + y2) / 2} ${x2},${(y1 + y2) / 2} ${x2},${y2}` : `M${x1},${y1} C${x1 + 60},${y1} ${x2 - 60},${y2} ${x2},${y2}`;
              return (
                <g key={`${a}-${b}`}>
                  <path d={d} fill="none" stroke="rgba(128,128,128,.35)" strokeWidth="2" />
                  <path d={d} fill="none" stroke={c} strokeWidth="2.4" className={`ns-flow ${st === "down" ? "is-down" : ""}`} />
                  <circle cx={x2} cy={y2} r="4" fill={c} />
                </g>
              );
            })}
            {Object.entries(NODES).map(([k, n]) => {
              const s = svcOf(k);
              const m = STATUS_META[s.status] || STATUS_META.unknown;
              return (
                <g key={k} className={`ns-node ${sel === k ? "is-sel" : ""} is-${s.status}`} transform={`translate(${n.x},${n.y})`} onClick={() => setSel(k)} style={{ cursor: "pointer" }}>
                  <rect width={W} height={H} rx="14" className="ns-box" stroke={sel === k ? m.color : "rgba(128,128,128,.4)"} />
                  <rect x="10" y="12" width="52" height="52" rx="12" className="ns-ic-bg" />
                  <svg x="20" y="22" width="32" height="32" viewBox="0 0 24 24">{G[n.icon]}</svg>
                  <text x="74" y="30" className="ns-title">{n.label}</text>
                  <text x="74" y="49" className="ns-sub">{n.sub}</text>
                  <text x="74" y="67" className="ns-metric" fill={m.color}>{m.label}</text>
                  {metric(s) && <text x={W - 12} y="67" textAnchor="end" className="ns-metric ns-metric-v">{metric(s)}</text>}
                  <circle cx={W - 16} cy="16" r="6" fill={m.color} className={s.status === "up" ? "ns-pulse" : ""} />
                </g>
              );
            })}
          </svg>
        </div>

        <aside className="ns-detail panel">
          <div className="ns-detail-head">
            <svg width="40" height="40" viewBox="0 0 24 24">{G[cur.icon]}</svg>
            <div><b>{cur.label}</b><span className="muted">{cur.sub}</span></div>
          </div>
          <span className="ns-badge" style={{ background: (STATUS_META[curSvc.status] || STATUS_META.unknown).color }}>{(STATUS_META[curSvc.status] || STATUS_META.unknown).label}</span>
          {curSvc.latency_ms !== undefined && <div className="ns-kv"><span>زمن الاستجابة</span><b className="mono">{curSvc.latency_ms}ms</b></div>}
          {curSvc.down_for_sec > 0 && <div className="ns-kv"><span>منقطع منذ</span><b className="mono">{Math.round(curSvc.down_for_sec)}ث</b></div>}
          {curSvc.unit && <div className="ns-kv"><span>خدمة النظام</span><b className="mono">{curSvc.unit}</b></div>}
          {Object.entries(curSvc.details || {}).map(([k, v]) => (
            <div key={k} className="ns-kv"><span>{DETAIL_LABEL[k] || k}</span><b className="mono">{Array.isArray(v) ? v.join(", ") || "—" : typeof v === "boolean" ? (v ? "نعم" : "لا") : v ?? "—"}</b></div>
          ))}
          {curSvc.note && <p className="ns-note">{curSvc.note}</p>}
          {curSvc.error && <p className="ns-err mono">{curSvc.error}</p>}
          {sel === "scheduler" && curSvc.jobs && (
            <div className="ns-jobs">
              <h3>المهام ({curSvc.jobs.length})</h3>
              {curSvc.jobs.map((j) => (
                <div key={j.id} className="ns-job">
                  <i style={{ background: !j.ok || j.missed ? "#ff6b5e" : j.last ? "#3ddc97" : "#6b6459" }} />
                  <span className="mono">{j.id}</span>
                  <small className="muted">{j.last ? `آخر ${new Date(j.last * 1000).toLocaleTimeString("en-GB")}` : "لم تعمل بعد"} · {j.next ? `التالي ${new Date(j.next * 1000).toLocaleTimeString("en-GB")}` : "—"}</small>
                </div>
              ))}
            </div>
          )}
          {!data && !error && <p className="muted">…جارٍ التحميل</p>}
        </aside>
      </div>

      {/* قائمة مختصرة للشاشات الصغيرة */}
      <div className="ns-list">
        {data && Object.entries(NODES).map(([k, n]) => {
          const s = svcOf(k);
          const m = STATUS_META[s.status] || STATUS_META.unknown;
          return (
            <button key={k} type="button" className={`ns-li ${sel === k ? "on" : ""}`} onClick={() => setSel(k)}>
              <svg width="30" height="30" viewBox="0 0 24 24">{G[n.icon]}</svg>
              <span><b>{n.label}</b><small style={{ color: m.color }}>{m.label}{metric(s) ? ` · ${metric(s)}` : ""}</small></span>
            </button>
          );
        })}
      </div>
    </>
  );
}
