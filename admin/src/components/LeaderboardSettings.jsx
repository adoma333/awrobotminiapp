import React, { useEffect, useState } from "react";
import { api } from "../api";

const TIERS = [
  ["bronze", "برونزي"], ["silver", "فضي"], ["gold", "ذهبي"], ["platinum", "بلاتيني"], ["diamond", "ماسي"], ["master", "أسطوري"],
];
const money = (v) => `$${Number(v || 0).toLocaleString("en-US")}`;
const GENDER = { girl: "girl", female: "girl", f: "girl", "أنثى": "girl", "فتاة": "girl", boy: "boy", male: "boy", m: "boy", "ذكر": "boy", "شاب": "boy" };
const TIER_KEYS = TIERS.map(([k]) => k);

// يقرأ ملف القائمة: JSON [{name, gender|avatar, tier, photo, usd}] أو CSV بعناوين: name,gender,tier,photo,usd
export function parseProfiles(text) {
  const t = text.replace(/^\uFEFF/, "").trim();
  let rows;
  if (t.startsWith("[")) rows = JSON.parse(t);
  else {
    const lines = t.split(/\r?\n/).filter((l) => l.trim());
    const split = (l) => l.split(/[,;\t]/).map((x) => x.trim().replace(/^"|"$/g, ""));
    const head = split(lines[0]).map((h) => h.toLowerCase());
    const hasHead = head.includes("name") || head.includes("الاسم");
    const cols = hasHead ? head : ["name", "gender", "tier", "photo", "usd"];
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
      base_usd: (() => {
        const v = String(r.usd ?? r.base_usd ?? r.profit ?? r["الربح"] ?? "").replace(/[$,\s]/g, "");
        return v === "" || Number.isNaN(Number(v)) ? null : Math.max(0, Number(v));
      })(),
    }))
    .filter((r) => r.name);
}

// تصغير الصورة مربّعًا 320px مع الحفاظ على صيغتها (JPG/PNG/WebP) قبل الرفع
const OUT_TYPE = { "image/png": "image/png", "image/webp": "image/webp" };
function toSquare(file) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const s = Math.min(img.width, img.height);
      const c = document.createElement("canvas");
      c.width = 320; c.height = 320;
      c.getContext("2d").drawImage(img, (img.width - s) / 2, (img.height - s) / 2, s, s, 0, 0, 320, 320);
      URL.revokeObjectURL(img.src);
      resolve(c.toDataURL(OUT_TYPE[file.type] || "image/jpeg", 0.86).split(",")[1]);
    };
    img.onerror = reject;
    img.src = URL.createObjectURL(file);
  });
}

const sig = ({ confirmed_at, ...c }) => JSON.stringify(c); // eslint-disable-line no-unused-vars
const MODES = { open: "مفتوح: كل المستخدمين الحقيقيين + الأسماء المُدارة", group: "مجموعة مغلقة: عدد ثابت يضم المستخدم نفسه" };

/** ترتيب أرباح الأسبوع: البيانات المؤكَّدة ثابتة، محرك المحاكاة ضمن حدود الأدمن، والأسماء والصور. */
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
      setSaved(sig(rest));
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
        const { url } = await api.leaderboardPhoto(await toSquare(f));
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
      setMsg(`استُوردت ${rows.length} اسمًا (معاينة فقط) — راجعها ثم اضغط «تأكيد وحفظ»`);
    } catch {
      setMsg("❌ ملف غير صالح. الصيغة: name,gender,tier,photo");
    }
  }

  async function rowPhoto(i, file) {
    try {
      const { url } = await api.leaderboardPhoto(await toSquare(file));
      setRow(i, { photo: url });
    } catch { setMsg("❌ تعذّر رفع الصورة"); }
  }

  async function save() {
    setMsg("");
    const changedProfiles = JSON.stringify(cfg.profiles) !== JSON.stringify(JSON.parse(saved).profiles);
    if (changedProfiles && !window.confirm(`تأكيد حفظ ${cfg.profiles.length} اسمًا؟\nبعد التأكيد تُثبَّت البيانات (الأسماء والصور والقيم الأساسية) ولا تتغير إلا بتأكيد جديد.`)) return;
    try {
      const { confirmed_at: _c, ...patch } = cfg; // eslint-disable-line no-unused-vars
      const body = changedProfiles ? patch : Object.fromEntries(Object.entries(patch).filter(([k]) => k !== "profiles"));
      const { default_profiles: _d, ...c } = await api.saveLeaderboard(body);
      setCfg(c);
      setSaved(sig(c));
      setMsg("✅ تم التأكيد والحفظ");
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
          <button className="primary" disabled={sig(cfg) === saved} onClick={save}>تأكيد وحفظ</button>
        </div>
      </div>
      <label className="check"><input type="checkbox" checked={cfg.enabled} onChange={(e) => set({ enabled: e.target.checked })} /> إظهار الأسماء المُدارة في الترتيب (يظهر أسفل القائمة سطر توضيحي واحد بأن بعض الأسماء عينات)</label>
      <p className="muted">آخر تأكيد للبيانات: <b className="mono">{cfg.confirmed_at ? new Date(cfg.confirmed_at * 1000).toLocaleString("ar-u-nu-latn") : "—"}</b> — القائمة ثابتة ولا تتغير عشوائيًا؛ تتغير فقط عند «تأكيد وحفظ» جديد.</p>
      <h3>طريقة العرض</h3>
      <div className="tabs">
        {Object.entries(MODES).map(([k, v]) => <button key={k} className={`tab ${cfg.mode === k ? "active" : ""}`} onClick={() => set({ mode: k })}>{v}</button>)}
      </div>
      <div className="grid-form">
        {cfg.mode === "group" ? (
          <label>العدد الظاهر (يشمل المستخدم الحقيقي)<input className="mono" type="number" min="3" max="50" value={cfg.group_size} onChange={(e) => set({ group_size: num(e.target.value) })} /></label>
        ) : (
          <label>عدد الأسماء المُدارة المعروضة<input className="mono" type="number" min="0" max="50" value={cfg.count} onChange={(e) => set({ count: num(e.target.value) })} /></label>
        )}
      </div>
      <h3>محرك المحاكاة الديناميكية</h3>
      <label className="check"><input type="checkbox" checked={cfg.dynamic} onChange={(e) => set({ dynamic: e.target.checked })} /> تحريك الأرقام تلقائيًا (ارتفاع/انخفاض/تبادل ترتيب) حول القيمة الأساسية المؤكَّدة</label>
      <div className="grid-form">
        <label>الفاصل بين كل حركة (دقيقة)<input className="mono" type="number" min="1" max="1440" value={Math.round(cfg.interval_sec / 60)} onChange={(e) => set({ interval_sec: Math.max(60, num(e.target.value) * 60) })} disabled={!cfg.dynamic} /></label>
        <label>أقصى ابتعاد عن القيمة الأساسية (±%)<input className="mono" type="number" min="0" max="60" value={cfg.volatility_pct} onChange={(e) => set({ volatility_pct: num(e.target.value) })} disabled={!cfg.dynamic} /></label>
      </div>
      <h3>نطاقات توليد القيمة الأساسية (للأسماء بلا قيمة مُدخلة — تُولَّد مرة واحدة وتثبت)</h3>
      <div className="grid-form">
        <label>عدد النخبة المتصدرة<input className="mono" type="number" min="0" max="10" value={cfg.elite_count} onChange={(e) => set({ elite_count: num(e.target.value) })} /></label>
        <label>ربح النخبة الأسبوعي — من ($)<input className="mono" type="number" min="0" value={cfg.elite_min} onChange={(e) => set({ elite_min: num(e.target.value) })} /></label>
        <label>ربح النخبة الأسبوعي — إلى ($)<input className="mono" type="number" min="0" value={cfg.elite_max} onChange={(e) => set({ elite_max: num(e.target.value) })} /></label>
        <label>ربح البقية — من ($)<input className="mono" type="number" min="0" value={cfg.base_min} onChange={(e) => set({ base_min: num(e.target.value) })} /></label>
        <label>ربح البقية — إلى ($)<input className="mono" type="number" min="0" value={cfg.base_max} onChange={(e) => set({ base_max: num(e.target.value) })} /></label>
      </div>
      <p className="muted">النخبة (أول {cfg.elite_count}): {money(cfg.elite_min)} – {money(cfg.elite_max)} · البقية: {money(cfg.base_min)} – {money(cfg.base_max)}. مع كل أسبوع جديد تعود الأرقام للقيم الأساسية المؤكَّدة.</p>

      <div className="topbar">
        <h3>الأسماء والصور والشارات ({cfg.profiles.length})</h3>
        <div className="row-gap">
          <button onClick={() => set({ profiles: defaults.map((p) => ({ ...p })) })}>استيراد الأسماء الحالية</button>
          <label className="file-btn">استيراد ملف (CSV/JSON)<input type="file" accept=".csv,.json,.txt" hidden onChange={(e) => e.target.files[0] && importFile(e.target.files[0])} /></label>
          <label className="file-btn">{busy ? "جارٍ الرفع…" : "رفع صور البروفايلات (JPG/PNG/WebP)"}<input type="file" accept="image/jpeg,image/png,image/webp" multiple hidden disabled={busy} onChange={(e) => uploadPhotos([...e.target.files])} /></label>
          <button onClick={() => set({ profiles: [...cfg.profiles, { name: "", avatar: "boy", tier: "gold", base_usd: null }] })}>+ اسم</button>
        </div>
      </div>
      <p className="muted">صيغة الملف: سطر لكل اسم <code>name,gender,tier,photo,usd</code> — gender: male/female، tier: bronze…master، photo: رابط أو اسم ملف صورة مرفوعة، usd: القيمة الأساسية لربح الأسبوع (اختياري). الاستيراد معاينة فقط حتى تضغط «تأكيد وحفظ».</p>
      <div className="scrollx">
        <table className="list keep">
          <thead><tr><th>#</th><th>الصورة</th><th>الاسم</th><th>النوع</th><th>الشارة</th><th>القيمة الأساسية ($)</th><th /></tr></thead>
          <tbody>
            {cfg.profiles.map((p, i) => (
              <tr key={i}>
                <td className="mono">{i + 1}</td>
                <td>
                  <label className="lb-photo" title="تغيير الصورة">
                    {p.photo ? <img src={p.photo} alt="" /> : <span>+</span>}
                    <input type="file" accept="image/jpeg,image/png,image/webp" hidden onChange={(e) => e.target.files[0] && rowPhoto(i, e.target.files[0])} />
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
                <td><input className="narrow" type="number" min="0" placeholder="تلقائي" value={p.base_usd ?? ""} onChange={(e) => setRow(i, { base_usd: e.target.value === "" ? null : Number(e.target.value) })} /></td>
                <td><button className="danger-ghost" onClick={() => set({ profiles: cfg.profiles.filter((_, j) => j !== i) })}>حذف</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
