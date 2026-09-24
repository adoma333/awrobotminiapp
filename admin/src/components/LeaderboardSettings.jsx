import React, { useEffect, useState } from "react";
import { api } from "../api";

const TIERS = [
  ["bronze", "برونزي"], ["silver", "فضي"], ["gold", "ذهبي"], ["platinum", "بلاتيني"], ["diamond", "ماسي"], ["master", "أسطوري"],
];
const money = (v) => `$${Number(v || 0).toLocaleString("en-US")}`;
const GENDER = { girl: "girl", female: "girl", f: "girl", "أنثى": "girl", "فتاة": "girl", boy: "boy", male: "boy", m: "boy", "ذكر": "boy", "شاب": "boy" };
const TIER_KEYS = TIERS.map(([k]) => k);

// يقرأ ملف القائمة: JSON [{name, gender|avatar, tier, photo}] أو CSV بعناوين: name,gender,tier,photo
export function parseProfiles(text) {
  const t = text.replace(/^\uFEFF/, "").trim();
  let rows;
  if (t.startsWith("[")) rows = JSON.parse(t);
  else {
    const lines = t.split(/\r?\n/).filter((l) => l.trim());
    const split = (l) => l.split(/[,;\t]/).map((x) => x.trim().replace(/^"|"$/g, ""));
    const head = split(lines[0]).map((h) => h.toLowerCase());
    const hasHead = head.includes("name") || head.includes("الاسم");
    const cols = hasHead ? head : ["name", "gender", "tier", "photo"];
    rows = (hasHead ? lines.slice(1) : lines).map((l) => {
      const v = split(l);
      const o = {};
      cols.forEach((c, i) => { o[c] = v[i]; });
      return o;
    });
  }
  return rows
    .map((r) => ({
      name: String(r.name || r["الاسم"] || "").trim(),
      avatar: GENDER[String(r.gender || r.avatar || r["النوع"] || "").trim().toLowerCase()] || "boy",
      tier: TIER_KEYS.includes(String(r.tier || "").toLowerCase()) ? String(r.tier).toLowerCase() : "gold",
      photo: String(r.photo || r.image || r["الصورة"] || "").trim(),
    }))
    .filter((r) => r.name);
}

// تصغير الصورة مربّعًا 320px (JPEG) قبل الرفع
function toJpeg(file) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const s = Math.min(img.width, img.height);
      const c = document.createElement("canvas");
      c.width = 320; c.height = 320;
      c.getContext("2d").drawImage(img, (img.width - s) / 2, (img.height - s) / 2, s, s, 0, 0, 320, 320);
      URL.revokeObjectURL(img.src);
      resolve(c.toDataURL("image/jpeg", 0.86).split(",")[1]);
    };
    img.onerror = reject;
    img.src = URL.createObjectURL(file);
  });
}

/** ترتيب أرباح الأسبوع: التشغيل، العدد، النخبة، نطاقات الأرباح بالدولار، والأسماء والصور والشارات. */
export default function LeaderboardSettings() {
  const [cfg, setCfg] = useState(null);
  const [defaults, setDefaults] = useState([]);
  const [saved, setSaved] = useState("");
  const [msg, setMsg] = useState("");
  const [photoMap, setPhotoMap] = useState({}); // اسم الملف → رابط الصورة المرفوعة
  const [busy, setBusy] = useState(false);

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

  async function uploadPhotos(files) {
    setBusy(true);
    const map = { ...photoMap };
    let n = 0;
    for (const f of files) {
      try {
        const { url } = await api.leaderboardPhoto(await toJpeg(f));
        map[f.name.toLowerCase()] = url;
        map[f.name.toLowerCase().replace(/\.[^.]+$/, "")] = url;
        n += 1;
      } catch { /* نتخطى الصورة التالفة */ }
    }
    setPhotoMap(map);
    // ربط الصور بالأسماء الموجودة حسب اسم الملف
    set({ profiles: cfg.profiles.map((p) => ({ ...p, photo: map[(p.photo || "").toLowerCase()] || map[p.name.toLowerCase()] || p.photo })) });
    setMsg(`✅ رُفعت ${n} صورة`);
    setBusy(false);
  }

  async function importFile(file) {
    try {
      const rows = parseProfiles(await file.text()).map((r) => ({
        ...r, photo: /^https?:\/\//.test(r.photo) ? r.photo : photoMap[r.photo.toLowerCase()] || photoMap[r.name.toLowerCase()] || "",
      }));
      if (!rows.length) throw new Error("empty");
      set({ profiles: rows });
      setMsg(`✅ استُوردت ${rows.length} اسمًا — راجعها ثم اضغط حفظ`);
    } catch {
      setMsg("❌ ملف غير صالح. الصيغة: name,gender,tier,photo");
    }
  }

  async function rowPhoto(i, file) {
    try {
      const { url } = await api.leaderboardPhoto(await toJpeg(file));
      setRow(i, { photo: url });
    } catch { setMsg("❌ تعذّر رفع الصورة"); }
  }

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
          <label className="file-btn">استيراد ملف (CSV/JSON)<input type="file" accept=".csv,.json,.txt" hidden onChange={(e) => e.target.files[0] && importFile(e.target.files[0])} /></label>
          <label className="file-btn">{busy ? "جارٍ الرفع…" : "رفع صور البروفايلات"}<input type="file" accept="image/*" multiple hidden disabled={busy} onChange={(e) => uploadPhotos([...e.target.files])} /></label>
          <button onClick={() => set({ profiles: [...cfg.profiles, { name: "", avatar: "boy", tier: "gold" }] })}>+ اسم</button>
        </div>
      </div>
      <p className="muted">صيغة الملف: سطر لكل منافس <code>name,gender,tier,photo</code> — gender: male/female، tier: bronze…master، photo: رابط أو اسم ملف صورة من الصور المرفوعة. ارفع الصور أولًا أو بعد الاستيراد، وتُربط تلقائيًا باسم الملف أو باسم المنافس.</p>
      <div className="scrollx">
        <table className="list keep">
          <thead><tr><th>#</th><th>الصورة</th><th>الاسم</th><th>النوع</th><th>الشارة</th><th /></tr></thead>
          <tbody>
            {cfg.profiles.map((p, i) => (
              <tr key={i}>
                <td className="mono">{i + 1}</td>
                <td>
                  <label className="lb-photo" title="تغيير الصورة">
                    {p.photo ? <img src={p.photo} alt="" /> : <span>+</span>}
                    <input type="file" accept="image/*" hidden onChange={(e) => e.target.files[0] && rowPhoto(i, e.target.files[0])} />
                  </label>
                </td>
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
