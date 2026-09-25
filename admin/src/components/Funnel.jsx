import React from "react";

const n = (v) => (v == null ? "—" : Number(v).toLocaleString("en-US"));

/** قمع التحويل: فتح التطبيق ← ربط الحساب ← أول دفعة ← تجديد، مع نسبة كل مرحلة وأين يتسرب المستخدمون. */
export default function Funnel({ f }) {
  if (!f) return null;
  const steps = [
    { k: "opened", label: "فتحوا التطبيق", v: f.opened },
    { k: "linked", label: "ربطوا حساب MT5", v: f.linked, rate: f.rates?.link, drop: f.dropoff?.not_linked },
    { k: "paid", label: "اشتركوا (أول دفعة)", v: f.paid, rate: f.rates?.pay, drop: f.dropoff?.linked_not_paid },
    { k: "renewed", label: "جدّدوا", v: f.renewed, rate: f.rates?.renew, drop: f.dropoff?.paid_not_renewed },
  ];
  const max = Math.max(1, f.opened || 0);
  return (
    <div className="funnel">
      {steps.map((s, i) => (
        <div className="funnel-step" key={s.k}>
          <div className="funnel-head">
            <span>{s.label}</span>
            <b className="mono">{n(s.v)}</b>
          </div>
          <div className="funnel-bar"><span style={{ width: `${Math.max(2, ((s.v || 0) / max) * 100)}%`, opacity: 1 - i * 0.16 }} /></div>
          {i > 0 && (
            <div className="funnel-meta muted">
              تحويل من المرحلة السابقة: <b className="mono">{s.rate == null ? "—" : `${s.rate}%`}</b> · توقفوا هنا: <b className="mono">{n(s.drop)}</b>
            </div>
          )}
        </div>
      ))}
      <div className="kv"><span>الإيرادات من هذه الفئة</span><b className="mono">${Number(f.revenue_usd || 0).toLocaleString("en-US")}</b></div>
    </div>
  );
}
