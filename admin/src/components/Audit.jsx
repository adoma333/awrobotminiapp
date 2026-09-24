import React, { useEffect, useState } from "react";
import { api } from "../api";

const ROLE_LABEL = { owner: "مالك", manager: "مدير", support: "دعم فني", viewer: "مشاهد" };
const when = (ts) => new Date(ts * 1000).toLocaleString("en-GB", { dateStyle: "short", timeStyle: "medium" });

/** سجل العمليات: كل تعديل في اللوحة مع صاحبه وعنوان IP ونوع الجهاز. */
export default function Audit() {
  const [rows, setRows] = useState(null);
  const [open, setOpen] = useState(null);
  const [admin, setAdmin] = useState("");
  useEffect(() => {
    const t = setTimeout(() => api.audit({ limit: 300, ...(admin ? { admin } : {}) }).then((r) => setRows(r.rows)).catch(() => setRows([])), 250);
    return () => clearTimeout(t);
  }, [admin]);

  return (
    <>
      <div className="topbar">
        <h1>سجل العمليات</h1>
        <input className="narrow-wide" inputMode="numeric" placeholder="تصفية بـ Telegram ID" value={admin} onChange={(e) => setAdmin(e.target.value.replace(/\D/g, ""))} />
      </div>
      {!rows && <p className="muted">...جارٍ التحميل</p>}
      {rows && rows.length === 0 && <div className="empty">لا عمليات مسجّلة بعد.</div>}
      <div className="audit-list">
        {(rows || []).map((r) => (
          <button key={r.id} className={`audit ${open === r.id ? "open" : ""}`} onClick={() => setOpen(open === r.id ? null : r.id)}>
            <div className="audit-top">
              <b>{r.action}</b>
              <span className={`badge ${r.status < 400 ? "approved" : "rejected"}`}>{r.status < 400 ? "تم" : `فشل ${r.status}`}</span>
            </div>
            <div className="audit-meta">
              <span className="mono">{when(r.at)}</span>
              <span>{ROLE_LABEL[r.role] || "—"} · <span className="mono">{r.admin_id}</span></span>
              <span className="mono">{r.ip || "—"}</span>
              <span>{[r.device?.model, r.device?.os, r.device?.browser].filter((x) => x && x !== "—").join(" · ") || "—"}</span>
            </div>
            {open === r.id && (
              <div className="audit-body">
                <div className="kv"><span>المسار</span><b className="mono">{r.method} {r.path}</b></div>
                <div className="kv"><span>الجهاز</span><b>{r.device?.type === "mobile" ? "جوال" : "حاسوب"}</b></div>
                {r.body && <pre className="mono">{r.body}</pre>}
                <p className="muted mono ua">{r.user_agent}</p>
              </div>
            )}
          </button>
        ))}
      </div>
    </>
  );
}
