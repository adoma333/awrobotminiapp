import React, { useCallback, useEffect, useState } from "react";

const LABEL = {
  firestore: "قاعدة البيانات (Firestore)",
  mt5_bridge: "جسر MT5 (Wine)",
  n8n: "تكامل n8n",
};

const STATUS_META = {
  up: { color: "#3ddc97", label: "يعمل" },
  degraded: { color: "#e5b84b", label: "بطيء" },
  down: { color: "#ff6b5e", label: "متوقف" },
  not_configured: { color: "#6b6459", label: "غير مُهيّأ" },
};

async function fetchStatus() {
  const res = await fetch("/api/system/status", { credentials: "include" });
  if (!res.ok) throw new Error(String(res.status));
  return res.json();
}

export default function SystemStatus() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    fetchStatus()
      .then((r) => {
        setData(r);
        setError("");
      })
      .catch(() => setError("تعذّر تحميل حالة النظام."));
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 30000); // تحديث حي كل 30 ثانية
    return () => clearInterval(id);
  }, [load]);

  return (
    <>
      <div className="topbar">
        <h1>حالة النظام</h1>
      </div>

      {error && <p style={{ color: "var(--bad)" }}>{error}</p>}

      {data && (
        <div className="stat-row" style={{ flexWrap: "wrap" }}>
          {Object.entries(data.services).map(([key, svc]) => {
            const meta = STATUS_META[svc.status] || STATUS_META.down;
            return (
              <div className="stat" key={key} style={{ minWidth: 220 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                  <span
                    style={{
                      width: 10,
                      height: 10,
                      borderRadius: "50%",
                      background: meta.color,
                      display: "inline-block",
                      boxShadow: `0 0 8px ${meta.color}`,
                    }}
                  />
                  <b style={{ fontSize: 14 }}>{meta.label}</b>
                </div>
                <span>{LABEL[key] || key}</span>
                {svc.latency_ms !== undefined && (
                  <span className="mono" style={{ display: "block", fontSize: 12, opacity: 0.7 }}>
                    {svc.latency_ms}ms
                  </span>
                )}
                {svc.error && (
                  <span className="mono" style={{ display: "block", fontSize: 11, color: "var(--bad)" }}>
                    {svc.error}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}

      {!data && !error && <p>...جارٍ التحميل</p>}
    </>
  );
}
