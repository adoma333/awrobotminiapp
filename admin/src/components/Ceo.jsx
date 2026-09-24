import React, { useEffect, useState } from "react";
import { api } from "../api";

const n = (v) => (v == null ? "—" : Number(v).toLocaleString("en-US"));
const usd = (v) => (v == null ? "—" : `$${Number(v).toLocaleString("en-US", { maximumFractionDigits: 2 })}`);
const METHOD = { nowpayments: "عملات رقمية", ton: "محفظة TON", stars: "نجوم تلجرام" };

// أعمدة بسيطة بلا مكتبات: قيمة كل يوم خلال 30 يومًا
function Bars({ rows, field, fmt, color }) {
  const max = Math.max(1, ...rows.map((r) => r[field]));
  return (
    <div className="bars" role="img">
      {rows.map((r) => (
        <div key={r.d} className="bar-col" title={`${r.d}: ${fmt(r[field])}`}>
          <span style={{ height: `${(r[field] / max) * 100}%`, background: color }} />
        </div>
      ))}
    </div>
  );
}

function Kpi({ label, value, hint, tone }) {
  return (
    <div className={`kpi ${tone || ""}`}>
      <span className="kpi-label">{label}</span>
      <b className="kpi-value mono">{value}</b>
      {hint && <span className="kpi-hint">{hint}</span>}
    </div>
  );
}

/** لوحة الرئيس التنفيذي: أرقام الأعمال بلغة بسيطة لأي عضو في الفريق. */
export default function Ceo() {
  const [d, setD] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    api.ceo().then(setD).catch(() => setErr("تعذّر تحميل الإحصاءات."));
  }, []);
  if (err) return <p className="error-text">{err}</p>;
  if (!d) return <p className="muted">...جارٍ التحميل</p>;
  const { users: u, subscriptions: s, revenue: r } = d;

  return (
    <>
      <div className="topbar">
        <h1>لوحة الرئيس التنفيذي</h1>
        <span className="muted">آخر تحديث: {new Date(d.generated_at * 1000).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}</span>
      </div>

      <h2 className="group-title">الإيرادات</h2>
      <div className="kpi-grid">
        <Kpi label="إجمالي الإيرادات" value={usd(r.total_usd)} hint={`${n(r.orders)} عملية دفع ناجحة`} tone="accent" />
        <Kpi label="آخر 30 يومًا" value={usd(r.last_30d_usd)} />
        <Kpi label="آخر 7 أيام" value={usd(r.last_7d_usd)} />
        <Kpi label="متوسط ما يدفعه المشترك" value={usd(r.arpu_usd)} hint={`نجوم تلجرام: ${n(r.stars_total)} ⭐`} />
      </div>

      <h2 className="group-title">المستخدمون والاشتراكات</h2>
      <div className="kpi-grid">
        <Kpi label="كل المستخدمين" value={n(u.total)} hint={`+${n(u.new_7d)} هذا الأسبوع · +${n(u.new_30d)} هذا الشهر`} />
        <Kpi label="حسابات MT5 مربوطة" value={n(u.linked)} />
        <Kpi label="اشتراكات فعّالة" value={n(s.active)} tone="ok" hint={`فترة تجريبية: ${n(s.trial)}`} />
        <Kpi label="اشتراكات منتهية" value={n(s.expired)} tone="bad" hint="فرصة لإعادة التواصل والتجديد" />
        <Kpi label="نسبة من دفع من المربوطين" value={s.conversion_pct == null ? "—" : `${s.conversion_pct}%`} hint={`${n(s.paying_users)} مستخدم دفع`} />
        <Kpi label="جاؤوا عبر الإحالة" value={n(u.referred)} />
      </div>

      <div className="two-col">
        <div className="panel">
          <h2>الإيرادات اليومية (30 يومًا)</h2>
          <Bars rows={d.series} field="revenue" fmt={usd} color="var(--accent)" />
          <div className="bars-axis"><span>{d.series[0]?.d.slice(5)}</span><span>{d.series[d.series.length - 1]?.d.slice(5)}</span></div>
        </div>
        <div className="panel">
          <h2>التسجيلات اليومية (30 يومًا)</h2>
          <Bars rows={d.series} field="signups" fmt={n} color="#1fa7a0" />
          <div className="bars-axis"><span>{d.series[0]?.d.slice(5)}</span><span>{d.series[d.series.length - 1]?.d.slice(5)}</span></div>
        </div>
      </div>

      <div className="two-col">
        <div className="panel">
          <h2>طرق الدفع</h2>
          {Object.keys(d.by_method).length === 0 && <p className="muted">لا مدفوعات بعد.</p>}
          {Object.entries(d.by_method).map(([k, v]) => (
            <div className="kv" key={k}><span>{METHOD[k] || k}</span><b>{n(v)}</b></div>
          ))}
        </div>
        <div className="panel">
          <h2>الباقات الأكثر مبيعًا</h2>
          {Object.keys(d.by_package).length === 0 && <p className="muted">لا مبيعات بعد.</p>}
          {Object.entries(d.by_package).map(([k, v]) => (
            <div className="kv" key={k}><span>{k}</span><b>{n(v)}</b></div>
          ))}
        </div>
      </div>
    </>
  );
}
