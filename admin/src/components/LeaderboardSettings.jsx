import React, { useEffect, useState } from "react";
import { api } from "../api";

const TIERS = [
  ["bronze", "برونزي"], ["silver", "فضي"], ["gold", "ذهبي"], ["platinum", "بلاتيني"], ["diamond", "ماسي"], ["master", "أسطوري"],
];
const money = (v) => `$${Number(v || 0).toLocaleString("en-US")}`;

/** ترتيب أرباح الأسبوع: التشغيل، العدد، النخبة، نطاقات الأرباح بالدولار، والأسماء والصور والشارات. */
export default function LeaderboardSettings() {
  const [cfg, setCfg] = useState(null);
  const [defaults, setDefaults] = useState([]);
  const [saved, setSaved] = useState("");
  const [msg, setMsg] = useState("");

  useEffect(() => {
    api.leaderboard().then((c) => {
      const { default_profiles: d, ...rest } = c;
      setDefaults(d || []);
      setCfg(rest);
      setSaved(JSON.stringify(rest));
    }).catch(() => setMsg("تعذّر تحميل إعدادات الترتيب."));
  }, []);

  if (!cfg) return <div className="panel"><h2>ترتيب أرباح الأسبوع</h2><p className="muted">{msg || "...جارٍ التحميل"}</p></div>;
  const set = (patch) => setCfg({ ...cfg, ...patch });
  const setRow = (i, patch) => set({ profiles: cfg.profiles.map((p, j) => (j === i ? { ...p, ...patch } : p)) });
  const num = (v) => (v === "" ? 0 : Number(v));

  async function save() {
    setMsg("");
    try {
      const { default_profiles: _d, ...c } = await api.saveLeaderboard(cfg);
      setCfg(c);
      setSaved(JSON.stringify(c));
      setMsg("✅ تم الحفظ");
    } catch (e) {
      setMsg(`❌ ${e.detail || "تعذّر الحفظ"}`);
    }
  }

  return (
    <div className="panel">
      <div className="topbar">
        <h2>ترتيب أرباح الأسبوع</h2>
        <div className="row-gap">
          {msg && <span className="muted">{msg}</span>}
          <button className="primary" disabled={JSON.stringify(cfg) === saved} onClick={save}>حفظ الترتيب</button>
        </div>
      </div>
      <label className="check"><input type="checkbox" checked={cfg.enabled} onChange={(e) => set({ enabled: e.target.checked })} /> إضافة منافسين محاكاة للسباق (تظهر بجانبهم علامة صغيرة وسطر توضيحي)</label>
      <div className="grid-form">
        <label>عدد المنافسين المعروضين<input className="mono" type="number" min="0" max="50" value={cfg.count} onChange={(e) => set({ count: num(e.target.value) })} /></label>
        <label>عدد النخبة المتصدرة<input className="mono" type="number" min="0" max="10" value={cfg.elite_count} onChange={(e) => set({ elite_count: num(e.target.value) })} /></label>
        <label>ربح النخبة الأسبوعي — من ($)<input className="mono" type="number" min="0" value={cfg.elite_min} onChange={(e) => set({ elite_min: num(e.target.value) })} /></label>
        <label>ربح النخبة الأسبوعي — إلى ($)<input className="mono" type="number" min="0" value={cfg.elite_max} onChange={(e) => set({ elite_max: num(e.target.value) })} /></label>
        <label>ربح البقية — من ($)<input className="mono" type="number" min="0" value={cfg.base_min} onChange={(e) => set({ base_min: num(e.target.value) })} /></label>
        <label>ربح البقية — إلى ($)<input className="mono" type="number" min="0" value={cfg.base_max} onChange={(e) => set({ base_max: num(e.target.value) })} /></label>
      </div>
      <p className="muted">النخبة: {money(cfg.elite_min)} – {money(cfg.elite_max)} · البقية: {money(cfg.base_min)} – {money(cfg.base_max)}. تُعاد القيم مع كل أسبوع وتتحرك كل 20 دقيقة، وتُطبَّق التعديلات فورًا.</p>

      <div className="topbar">
        <h3>الأسماء والصور والشارات ({cfg.profiles.length})</h3>
        <div className="row-gap">
          <button onClick={() => set({ profiles: defaults.map((p) => ({ ...p })) })}>استيراد الأسماء الحالية</button>
          <button onClick={() => set({ profiles: [...cfg.profiles, { name: "", avatar: "boy", tier: "gold" }] })}>+ اسم</button>
        </div>
      </div>
      <div className="scrollx">
        <table className="list keep">
          <thead><tr><th>#</th><th>الاسم</th><th>الصورة</th><th>الشارة</th><th /></tr></thead>
          <tbody>
            {cfg.profiles.map((p, i) => (
              <tr key={i}>
                <td className="mono">{i + 1}</td>
                <td><input value={p.name} maxLength={32} onChange={(e) => setRow(i, { name: e.target.value })} /></td>
                <td>
                  <select value={p.avatar} onChange={(e) => setRow(i, { avatar: e.target.value })}>
                    <option value="boy">شاب</option>
                    <option value="girl">فتاة</option>
                  </select>
                </td>
                <td>
                  <select value={p.tier} onChange={(e) => setRow(i, { tier: e.target.value })}>
                    {TIERS.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                </td>
                <td><button className="danger-ghost" onClick={() => set({ profiles: cfg.profiles.filter((_, j) => j !== i) })}>حذف</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
