import React, { useEffect, useRef, useState } from "react";
import { api } from "../api";

const SEEN_KEY = "aw_admin_alerts_seen";
const POLL_MS = 20000;
const LEVEL_CLS = { critical: "rejected", warn: "pending", info: "approved" };
const when = (ts) => new Date(ts * 1000).toLocaleString("ar-u-nu-latn", { dateStyle: "short", timeStyle: "short" });

/** تنبيهات فورية داخل اللوحة: خطأ حرج، تذكرة عاجلة/مصعّدة، دفعة كبيرة، عطل في النظام. */
export default function Alerts({ onGo }) {
  const [alerts, setAlerts] = useState([]);
  const [open, setOpen] = useState(false);
  const [toasts, setToasts] = useState([]);
  const [seen, setSeen] = useState(() => Number(localStorage.getItem(SEEN_KEY) || 0));
  const known = useRef(null);
  const box = useRef(null);

  useEffect(() => {
    let alive = true;
    const poll = () =>
      api.alerts(0).then((r) => {
        if (!alive) return;
        const rows = r.alerts || [];
        if (known.current) {
          const fresh = rows.filter((a) => !known.current.has(a.id));
          if (fresh.length) {
            setToasts((t) => [...fresh.slice(0, 3), ...t].slice(0, 4));
            fresh.slice(0, 3).forEach((a) => setTimeout(() => setToasts((t) => t.filter((x) => x.id !== a.id)), 9000));
          }
        }
        known.current = new Set(rows.map((a) => a.id));
        setAlerts(rows);
      }).catch(() => {});
    poll();
    const id = setInterval(poll, POLL_MS);
    return () => { alive = false; clearInterval(id); };
  }, []);

  useEffect(() => {
    if (!open) return undefined;
    const onDoc = (e) => box.current && !box.current.contains(e.target) && setOpen(false);
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const unread = alerts.filter((a) => a.at > seen).length;
  function toggle() {
    const next = !open;
    setOpen(next);
    if (next && alerts[0]) {
      const ts = alerts[0].at;
      setSeen(ts);
      try { localStorage.setItem(SEEN_KEY, String(ts)); } catch { /* تخزين غير متاح */ }
    }
  }
  function go(a) {
    setOpen(false);
    onGo(a.page);
  }

  return (
    <div className="alerts" ref={box}>
      <button className="alerts-btn" onClick={toggle} aria-label="التنبيهات">
        <svg viewBox="0 0 24 24" width="19" height="19" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15ZM10 20.5a2.2 2.2 0 0 0 4 0" /></svg>
        {unread > 0 && <span className="alerts-count mono">{unread > 99 ? "99+" : unread}</span>}
      </button>
      {open && (
        <div className="alerts-panel">
          <div className="alerts-head"><b>التنبيهات الفورية</b><span className="muted">آخر 7 أيام</span></div>
          {alerts.length === 0 ? <p className="muted" style={{ padding: 14 }}>لا تنبيهات. كل شيء يعمل بشكل طبيعي.</p> : alerts.map((a) => (
            <button key={a.id} className={`alert-item ${a.at > seen ? "is-new" : ""}`} onClick={() => go(a)}>
              <span className={`badge ${LEVEL_CLS[a.level]}`}>{a.level === "critical" ? "حرج" : a.level === "warn" ? "مهم" : "معلومة"}</span>
              <div><b>{a.title}</b><span className="muted">{a.text}</span><small className="muted mono">{when(a.at)}</small></div>
            </button>
          ))}
        </div>
      )}
      <div className="alert-toasts">
        {toasts.map((a) => (
          <button key={a.id} className={`alert-toast lvl-${a.level}`} onClick={() => go(a)}>
            <b>{a.title}</b><span>{a.text}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
