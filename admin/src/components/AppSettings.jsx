import React, { useEffect, useState } from "react";
import { api } from "../api";

/** الإعدادات العامة (config/settings): سياسة التسجيل، الرافعة، الإحالة، إيقاف التسجيل، والفترة التجريبية. */
export default function AppSettings() {
  const [s, setS] = useState(null);
  const [saved, setSaved] = useState("");
  const [msg, setMsg] = useState("");

  useEffect(() => {
    api.settings().then((x) => { setS(x); setSaved(JSON.stringify(x)); }).catch(() => setMsg("تعذّر التحميل."));
  }, []);

  if (!s) return <p>{msg || "...جارٍ التحميل"}</p>;
  const set = (patch) => setS({ ...s, ...patch });
  const num = (v) => (v === "" ? 0 : Number(v));

  async function save() {
    setMsg("");
    try {
      const x = await api.saveSettings(s);
      setS(x);
      setSaved(JSON.stringify(x));
      setMsg("✅ تم الحفظ");
    } catch (e) {
      setMsg(`❌ ${e.detail || "تعذّر الحفظ"}`);
    }
  }

  return (
    <>
      <div className="topbar">
        <h1>مركز التحكم</h1>
        <div className="row-gap">
          {msg && <span className="muted">{msg}</span>}
          <button className="primary" disabled={JSON.stringify(s) === saved} onClick={save}>حفظ</button>
        </div>
      </div>

      <div className="panel">
        <h2>طرق الدفع</h2>
        <label className="check"><input type="checkbox" checked={s.pay_ton_enabled} disabled /> محفظة TON (TON Connect) — تُدار من صفحة «محفظة TON» برمز تحقق</label>
        <label className="check"><input type="checkbox" checked={s.pay_crypto_enabled} onChange={(e) => set({ pay_crypto_enabled: e.target.checked })} /> العملات الرقمية (بوابة NOWPayments المخصّصة)</label>
        <label className="check"><input type="checkbox" checked={s.pay_stars_enabled} onChange={(e) => set({ pay_stars_enabled: e.target.checked })} /> نجوم تلجرام</label>
        <p className="muted">إيقاف أي طريقة يخفيها من التطبيق فورًا ويرفضها الخادم أيضًا.</p>
      </div>

      <div className="panel">
        <h2>شريط الإعلان والتنبيهات</h2>
        <p className="muted">قناة الدعم (البوت، الحساب البشري، الهاتف) أصبحت في «الدعم الفني الذكي»، ونافذة التحديثات المنبثقة في «نافذة التحديثات».</p>
        <div className="grid-form">
          <label>تنبيه فوري في اللوحة لأي دفعة من ($)<input className="mono" type="number" min="0" value={s.alert_large_payment_usd ?? 400} onChange={(e) => set({ alert_large_payment_usd: Number(e.target.value) })} /></label>
        </div>
        <div className="grid-form">
          <label>إعلان أعلى الرئيسية (عربي)<textarea rows={2} value={s.announcement_ar} onChange={(e) => set({ announcement_ar: e.target.value })} /></label>
          <label>Announcement (English)<textarea rows={2} dir="ltr" value={s.announcement_en} onChange={(e) => set({ announcement_en: e.target.value })} /></label>
        </div>
        <p className="muted">اترك الإعلان فارغًا لإخفائه.</p>
      </div>

      <div className="panel">
        <h2>التسجيل والربط</h2>
        <label className="check danger"><input type="checkbox" checked={s.kill_switch} onChange={(e) => set({ kill_switch: e.target.checked })} /> إيقاف ربط الحسابات الجديدة مؤقتًا (Kill switch)</label>
        <div className="grid-form">
          <label>أنواع الحسابات المقبولة
            <select value={s.registration_policy} onChange={(e) => set({ registration_policy: e.target.value })}>
              <option value="both">حقيقي وتجريبي</option>
              <option value="real">حقيقي فقط</option>
              <option value="demo">تجريبي فقط</option>
            </select>
          </label>
          <label>أقل رافعة (0 = بلا حد)<input className="mono" type="number" min="0" value={s.leverage_min} onChange={(e) => set({ leverage_min: num(e.target.value) })} /></label>
          <label>أعلى رافعة (0 = بلا حد)<input className="mono" type="number" min="0" value={s.leverage_max} onChange={(e) => set({ leverage_max: num(e.target.value) })} /></label>
        </div>
      </div>

      <div className="panel">
        <h2>الإحالة</h2>
        <label className="check"><input type="checkbox" checked={s.referral_enabled} onChange={(e) => set({ referral_enabled: e.target.checked })} /> مكافأة الإحالة مفعّلة (أيام للطرفين عند أول دفعة)</label>
        <div className="grid-form">
          <label>أيام المكافأة<input className="mono" type="number" min="0" value={s.referral_days} onChange={(e) => set({ referral_days: num(e.target.value) })} /></label>
        </div>
      </div>

      <div className="panel">
        <h2>الفترة التجريبية للتداول الآلي</h2>
        <label className="check"><input type="checkbox" checked={s.trial_enabled} onChange={(e) => set({ trial_enabled: e.target.checked })} /> منح فترة تجريبية عند أول ربط (حساب سنت أو لوت محدود)</label>
        <div className="grid-form">
          <label>المدة (3–7 أيام)<input className="mono" type="number" min="3" max="7" value={s.trial_days} onChange={(e) => set({ trial_days: num(e.target.value) })} /></label>
          <label>أقصى لوت للحسابات العادية (0 = سنت فقط)<input className="mono" type="number" min="0" step="0.01" value={s.trial_max_lot} onChange={(e) => set({ trial_max_lot: num(e.target.value) })} /></label>
        </div>
      </div>
    </>
  );
}
