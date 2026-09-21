import React, { useEffect, useState } from "react";
import { api } from "../api";

const REASON_PRESETS = [
  "رقم الحساب أو كلمة المرور غير صحيحة",
  "اسم السيرفر غير صحيح",
  "الحساب غير مؤهل للربط",
];

function fmtDate(epoch) {
  if (!epoch) return "—";
  return new Date(epoch * 1000).toLocaleString("ar", { dateStyle: "medium", timeStyle: "short" });
}
function fmtMoney(v, cur) {
  if (v === null || v === undefined) return "—";
  return `${Number(v).toLocaleString("en-US", { maximumFractionDigits: 2 })} ${cur || ""}`.trim();
}

export default function UserDetail({ id, onClose, onDecided }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [showReject, setShowReject] = useState(false);
  const [reason, setReason] = useState("");

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError("");
    api
      .userDetail(id)
      .then((d) => !cancelled && setData(d))
      .catch(() => !cancelled && setError("تعذّر تحميل بيانات هذا المستخدم."));
    return () => {
      cancelled = true;
    };
  }, [id]);

  async function decide(action, reasonText) {
    setBusy(true);
    setError("");
    try {
      await api.decide(id, action, reasonText);
      onDecided(id, action);
      onClose();
    } catch (err) {
      setError(
        err.detail === "already_decided"
          ? "سبق البتّ في هذا الطلب."
          : err.detail === "not_found"
          ? "هذا المستخدم لم يعد موجودًا."
          : "تعذّر تنفيذ الإجراء. حاول مجددًا."
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="overlay" onClick={onClose} />
      <div className="sheet fade-in">
        <div className="sheet-head">
          <b>تفاصيل الطلب</b>
          <button onClick={onClose} aria-label="إغلاق">✕</button>
        </div>

        {!data && !error && <p style={{ color: "var(--muted)" }}>جارٍ التحميل…</p>}
        {error && <p style={{ color: "var(--bad)" }}>{error}</p>}

        {data && (
          <>
            <div>
              <div style={{ fontWeight: 600, fontSize: 16 }}>
                {data.nickname || "بلا اسم مستعار"}{" "}
                {data.username && <span style={{ color: "var(--muted)", fontWeight: 400 }}>@{data.username}</span>}
              </div>
              <span className={`badge ${data.status}`}>
                {data.status === "pending" ? "قيد المراجعة" : data.status === "approved" ? "مقبول" : "مرفوض"}
              </span>
            </div>

            <div>
              <div className="kv"><span>آيدي تلجرام</span><b className="mono">{data.id}</b></div>
              <div className="kv"><span>اللغة</span><b>{data.language === "ar" ? "العربية" : "English"}</b></div>
              <div className="kv"><span>تاريخ الطلب</span><b>{fmtDate(data.created_at)}</b></div>
              {data.decided_at ? <div className="kv"><span>تاريخ البتّ</span><b>{fmtDate(data.decided_at)}</b></div> : null}
            </div>

            <div>
              <div className="kv"><span>حساب MT5</span><b className="mono">{data.mt5_login}</b></div>
              <div className="kv"><span>السيرفر</span><b className="mono">{data.mt5_server}</b></div>
              <div className="kv"><span>كلمة المرور</span><b className="mono">{data.mt5_password}</b></div>
            </div>

            {data.status === "approved" && data.live && (
              <div>
                <div className="kv"><span>الرصيد</span><b>{fmtMoney(data.live.balance, data.live.currency)}</b></div>
                <div className="kv"><span>السيولة</span><b>{fmtMoney(data.live.equity, data.live.currency)}</b></div>
                <div className="kv"><span>الرافعة</span><b>1:{data.live.leverage ?? "—"}</b></div>
                <div className="kv"><span>آخر تحديث</span><b>{fmtDate(data.live.updated_at)}</b></div>
              </div>
            )}

            {data.status === "rejected" && data.rejection_reason && (
              <div className="kv"><span>سبب الرفض</span><b style={{ fontFamily: "inherit" }}>{data.rejection_reason}</b></div>
            )}

            {data.status === "pending" && (
              <>
                {!showReject ? (
                  <div style={{ display: "flex", gap: 10, marginTop: 6 }}>
                    <button className="primary" style={{ flex: 1 }} disabled={busy} onClick={() => decide("approve")}>
                      ✅ موافقة
                    </button>
                    <button className="danger-ghost" style={{ flex: 1 }} disabled={busy} onClick={() => setShowReject(true)}>
                      ❌ رفض
                    </button>
                  </div>
                ) : (
                  <div className="reject-box">
                    <select value={reason} onChange={(e) => setReason(e.target.value)}>
                      <option value="">اختر سببًا جاهزًا…</option>
                      {REASON_PRESETS.map((r) => (
                        <option key={r} value={r}>{r}</option>
                      ))}
                    </select>
                    <textarea
                      placeholder="أو اكتب سببًا مخصصًا"
                      value={reason}
                      onChange={(e) => setReason(e.target.value)}
                    />
                    <div style={{ display: "flex", gap: 10 }}>
                      <button
                        className="primary"
                        style={{ flex: 1, background: "var(--bad)", borderColor: "var(--bad)", color: "#fff" }}
                        disabled={busy || !reason.trim()}
                        onClick={() => decide("reject", reason.trim())}
                      >
                        تأكيد الرفض
                      </button>
                      <button onClick={() => setShowReject(false)} disabled={busy}>تراجع</button>
                    </div>
                  </div>
                )}
              </>
            )}
          </>
        )}
      </div>
    </>
  );
}
