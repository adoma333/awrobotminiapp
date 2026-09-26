import React, { useMemo, useState } from "react";
import { messages } from "@app/i18n.js";
import { Color, DragList, Group, IconPicker, Range, Seg, Text, Toggle } from "./controls";

export const BLOCK_LABEL = {
  who: "الاسم والحساب", feedback: "بطاقة التقييم", hero: "بطاقة الرصيد", announce: "شريط الإعلان", subscription: "حالة الاشتراك",
  scratch: "بطاقة الكشط الجديدة", quick: "الاختصارات السريعة", growth: "مربعات الأداء",
  logo: "الشعار", stepper: "مؤشر الخطوات", title: "العنوان", options: "اختيار اللغة", perks: "الميزات",
};
const QUICK_LABEL = { support: "الدعم الفني", notifications: "الإشعارات", billing: "سجل المدفوعات", faq: "الأسئلة الشائعة", calc: "حاسبة الأرباح",
  plans: "الباقات", rewards: "المكافآت", referral: "الإحالة", analytics: "التحليلات", settings: "الإعدادات" };
const CELL_LABEL = { today: "اليوم", week: "هذا الأسبوع", month: "هذا الشهر", all: "الإجمالي", winrate: "نسبة الربح", trades: "عدد الصفقات", profit_factor: "عامل الربح", drawdown: "أقصى تراجع" };
const NAV_LABEL = { main: "الرئيسية", analytics: "التحليلات", referral: "الإحالة", rewards: "المكافآت", plans: "الباقات", settings: "الإعدادات" };
const COLOR_LABEL = { accent: "اللون الرئيسي", accent2: "اللون الثانوي (التدرج)", bg: "الخلفية", surface: "البطاقات", text: "النص", muted: "النص الثانوي", ok: "الربح/النجاح", danger: "الخسارة/الخطأ" };

// ─────────── عام: الألوان والخطوط والأشكال والتكيّف مع الأجهزة ───────────
export function GlobalPanel({ d, set }) {
  const t = d.tokens;
  const tok = (patch) => set({ ...d, tokens: { ...t, ...patch } });
  const col = (mode, k, v) => tok({ [mode]: { ...t[mode], [k]: v } });
  return (
    <>
      <Group title="🎨 ألوان الوضع الليلي">
        <div className="st-colors">{Object.keys(COLOR_LABEL).map((k) => <Color key={k} label={COLOR_LABEL[k]} value={t.dark[k]} onChange={(v) => col("dark", k, v)} />)}</div>
      </Group>
      <Group title="☀️ ألوان الوضع النهاري" open={false}>
        <div className="st-colors">{Object.keys(COLOR_LABEL).map((k) => <Color key={k} label={COLOR_LABEL[k]} value={t.light[k]} onChange={(v) => col("light", k, v)} />)}</div>
      </Group>
      <Group title="🔤 الخطوط والحجم">
        <Seg label="خط النصوص" value={t.font_body} options={[["plex", "IBM Plex Arabic"], ["chakra", "Chakra Petch"], ["system", "خط الجهاز"]]} onChange={(v) => tok({ font_body: v })} />
        <Seg label="خط العناوين والأرقام" value={t.font_display} options={[["chakra", "Chakra Petch"], ["plex", "IBM Plex Arabic"], ["system", "خط الجهاز"]]} onChange={(v) => tok({ font_display: v })} />
        <Range label="حجم الواجهة كاملة" value={t.ui_scale} min={80} max={130} unit="%" onChange={(v) => tok({ ui_scale: v })} />
      </Group>
      <Group title="🧩 الأشكال">
        <Seg label="شكل الأزرار" value={t.button_shape} options={[["angled", "مائل (AW)"], ["rounded", "مستدير"], ["pill", "كبسولة"], ["square", "حاد"]]} onChange={(v) => tok({ button_shape: v })} />
        <Seg label="نمط البطاقات" value={t.card_style} options={[["glass", "زجاجي"], ["solid", "مصمت"], ["outline", "حدود فقط"], ["gradient", "متدرج"]]} onChange={(v) => tok({ card_style: v })} />
        <Range label="استدارة الزوايا" value={t.radius} min={0} max={32} unit="px" onChange={(v) => tok({ radius: v })} />
        <Range label="قوة التوهج" value={t.glow} min={0} max={100} unit="%" onChange={(v) => tok({ glow: v })} />
      </Group>
      <Group title="📱 التناسق مع كل الأجهزة">
        <Toggle label="تكيّف تلقائي مع حجم الشاشة" hint="يكبّر الواجهة قليلًا في الهواتف الكبيرة ويصغّرها في الصغيرة" value={t.fluid} onChange={(v) => tok({ fluid: v })} />
        <Range label="أقصى عرض للمحتوى (تابلت/كمبيوتر)" value={t.max_width} min={360} max={760} unit="px" onChange={(v) => tok({ max_width: v })} />
        <Seg label="الكثافة" value={t.density} options={[["compact", "مضغوطة"], ["comfortable", "مريحة"], ["spacious", "واسعة"]]} onChange={(v) => tok({ density: v })} />
      </Group>
      <Group title="✨ الحركة والوضع الافتراضي">
        <Toggle label="الحركات والانتقالات" value={t.animations} onChange={(v) => tok({ animations: v })} />
        <Seg label="الوضع عند أول فتح" value={t.default_theme} options={[["dark", "ليلي"], ["light", "نهاري"], ["auto", "حسب تلجرام"]]} onChange={(v) => tok({ default_theme: v })} />
      </Group>
    </>
  );
}

function BlocksEditor({ blocks, onChange }) {
  return (
    <DragList items={blocks} onChange={onChange} render={(b) => (
      <label className="st-block">
        <input type="checkbox" checked={b.visible} onChange={(e) => onChange(blocks.map((x) => (x.id === b.id ? { ...x, visible: e.target.checked } : x)))} />
        <span className={b.visible ? "" : "muted"}>{BLOCK_LABEL[b.id] || b.id}</span>
      </label>
    )} />
  );
}

// ─────────── صفحة البداية ───────────
export function StartPanel({ d, setPage, icons, askAi }) {
  const p = d.pages.start;
  const upd = (patch) => setPage("start", { ...p, ...patch });
  return (
    <>
      <Group title="↕️ ترتيب العناصر (اسحب وأفلت)" hint="اسحب العنصر لتغيير مكانه، وأزل العلامة لإخفائه.">
        <BlocksEditor blocks={p.blocks} onChange={(blocks) => upd({ blocks })} />
      </Group>
      <Group title="🖼 الشعار"><Range label="حجم الشعار" value={p.logo_size} min={32} max={96} unit="px" onChange={(v) => upd({ logo_size: v })} /></Group>
      <Group title="⭐ الميزات" hint="نص فارغ = النص الافتراضي. يمكنك إضافة حتى 6 ميزات.">
        <DragList items={p.perks.map((x, i) => ({ ...x, id: `p${i}` }))} onChange={(rows) => upd({ perks: rows.map(({ id, ...x }) => x) })} render={(x, i) => (
          <div className="st-row">
            <IconPicker value={x.icon} icons={icons} label={x.text_ar || x.text_en || `ميزة ${i + 1}`} askAi={askAi}
              onChange={(icon) => upd({ perks: p.perks.map((y, j) => (j === i ? { ...y, icon } : y)) })} />
            <input placeholder="بالعربية" value={x.text_ar} maxLength={80} onChange={(e) => upd({ perks: p.perks.map((y, j) => (j === i ? { ...y, text_ar: e.target.value } : y)) })} />
            <input dir="ltr" placeholder="English" value={x.text_en} maxLength={80} onChange={(e) => upd({ perks: p.perks.map((y, j) => (j === i ? { ...y, text_en: e.target.value } : y)) })} />
            <button type="button" className="danger-ghost" onClick={() => upd({ perks: p.perks.filter((_, j) => j !== i) })}>✕</button>
          </div>
        )} />
        {p.perks.length < 6 && <button type="button" onClick={() => upd({ perks: [...p.perks, { icon: "star", text_ar: "", text_en: "" }] })}>+ ميزة</button>}
      </Group>
    </>
  );
}

// ─────────── الرئيسية ───────────
export function HomePanel({ d, setPage, icons, catalog, askAi }) {
  const p = d.pages.home;
  const upd = (patch) => setPage("home", { ...p, ...patch });
  const hero = (patch) => upd({ hero: { ...p.hero, ...patch } });
  const items = p.quick.items;
  const unused = catalog.quick_items.filter((id) => !items.some((x) => x.id === id));
  const navIds = d.pages.nav.items.filter((x) => x.visible).map((x) => x.id);
  return (
    <>
      <Group title="↕️ ترتيب عناصر الرئيسية (اسحب وأفلت)" hint="كل عنصر يمكن إخفاؤه أو نقله لأي مكان.">
        <BlocksEditor blocks={p.blocks} onChange={(blocks) => upd({ blocks })} />
      </Group>
      <Group title="💰 بطاقة الرصيد">
        <Range label="حجم رقم الرصيد" value={p.hero.balance_size} min={70} max={140} unit="%" onChange={(v) => hero({ balance_size: v })} />
        <Toggle label="زر إخفاء الرصيد 👁" value={p.hero.eye} onChange={(v) => hero({ eye: v })} />
        <Toggle label="منحنى الأرباح" value={p.hero.sparkline} onChange={(v) => hero({ sparkline: v })} />
        <Toggle label="ربح اليوم بجانب النسبة" value={p.hero.today} onChange={(v) => hero({ today: v })} />
        <Toggle label="السيولة والربح العائم ومستوى الهامش" value={p.hero.stats} onChange={(v) => hero({ stats: v })} />
      </Group>
      <Group title="⚡ الاختصارات السريعة" hint="تجنّب تكرار ما في الشريط السفلي — العناصر المكررة معلّمة بـ ⚠️.">
        <Range label="عدد الأعمدة" value={p.quick.columns} min={2} max={5} onChange={(v) => upd({ quick: { ...p.quick, columns: v } })} />
        <DragList items={items} onChange={(rows) => upd({ quick: { ...p.quick, items: rows } })} render={(x, i) => (
          <div className="st-row">
            <IconPicker value={x.icon} icons={icons} label={QUICK_LABEL[x.id]} askAi={askAi} onChange={(icon) => upd({ quick: { ...p.quick, items: items.map((y, j) => (j === i ? { ...y, icon } : y)) } })} />
            <b>{QUICK_LABEL[x.id]}{navIds.includes(x.id) && <span title="موجود في الشريط السفلي"> ⚠️</span>}</b>
            <input placeholder="اسم مخصص (عربي)" value={x.label_ar || ""} maxLength={24} onChange={(e) => upd({ quick: { ...p.quick, items: items.map((y, j) => (j === i ? { ...y, label_ar: e.target.value } : y)) } })} />
            <input dir="ltr" placeholder="Custom (EN)" value={x.label_en || ""} maxLength={24} onChange={(e) => upd({ quick: { ...p.quick, items: items.map((y, j) => (j === i ? { ...y, label_en: e.target.value } : y)) } })} />
            <button type="button" className="danger-ghost" onClick={() => upd({ quick: { ...p.quick, items: items.filter((_, j) => j !== i) } })}>✕</button>
          </div>
        )} />
        {unused.length > 0 && items.length < 8 && (
          <div className="st-chips">{unused.map((id) => (
            <button key={id} type="button" onClick={() => upd({ quick: { ...p.quick, items: [...items, { id, icon: { support: "headset", notifications: "bell", billing: "history", faq: "question", calc: "calc", plans: "plans", rewards: "rewards", referral: "referral", analytics: "analytics", settings: "settings" }[id] }] } })}>
              + {QUICK_LABEL[id]}{navIds.includes(id) ? " ⚠️" : ""}
            </button>
          ))}</div>
        )}
      </Group>
      <Group title="📊 مربعات الأداء" hint="اختر 2 أو 4 أو 6 مربعات. تجنّب ما يظهر في بطاقة الرصيد (الإجمالي واليوم).">
        <div className="st-chips">
          {catalog.growth_cells.map((c) => {
            const on = p.growth.cells.includes(c);
            return <button key={c} type="button" className={on ? "on" : ""} onClick={() => upd({ growth: { cells: on ? p.growth.cells.filter((x) => x !== c) : [...p.growth.cells, c].slice(0, 6) } })}>{on ? "✓ " : "+ "}{CELL_LABEL[c]}</button>;
          })}
        </div>
        {p.growth.cells.length % 2 === 1 && <p className="error-text">اختر عددًا زوجيًا من المربعات (سيُحذف الأخير عند الحفظ).</p>}
      </Group>
    </>
  );
}

// ─────────── الشريط السفلي والعلوي ───────────
export function NavPanel({ d, setPage, icons, askAi }) {
  const p = d.pages.nav;
  const tb = d.pages.topbar;
  const upd = (patch) => setPage("nav", { ...p, ...patch });
  return (
    <>
      <Group title="📌 الشريط السفلي (اسحب لترتيب الأزرار)">
        <Toggle label="إظهار أسماء الأزرار" value={p.labels} onChange={(v) => upd({ labels: v })} />
        <DragList items={p.items} onChange={(items) => upd({ items })} render={(x, i) => (
          <div className="st-row">
            <input type="checkbox" checked={x.visible} disabled={x.id === "main"} onChange={(e) => upd({ items: p.items.map((y, j) => (j === i ? { ...y, visible: e.target.checked } : y)) })} />
            <IconPicker value={x.icon} icons={icons} label={NAV_LABEL[x.id]} askAi={askAi} onChange={(icon) => upd({ items: p.items.map((y, j) => (j === i ? { ...y, icon } : y)) })} />
            <b>{NAV_LABEL[x.id]}</b>
            <input placeholder="اسم مخصص" value={x.label_ar || ""} maxLength={20} onChange={(e) => upd({ items: p.items.map((y, j) => (j === i ? { ...y, label_ar: e.target.value } : y)) })} />
            <input dir="ltr" placeholder="Custom" value={x.label_en || ""} maxLength={20} onChange={(e) => upd({ items: p.items.map((y, j) => (j === i ? { ...y, label_en: e.target.value } : y)) })} />
          </div>
        )} />
      </Group>
      <Group title="🔝 الشريط العلوي">
        <Range label="حجم الشعار" value={tb.logo_size} min={18} max={44} unit="px" onChange={(v) => setPage("topbar", { ...tb, logo_size: v })} />
        <Toggle label="زر الوضع الليلي/النهاري" value={tb.theme_toggle} onChange={(v) => setPage("topbar", { ...tb, theme_toggle: v })} />
        <Toggle label="زر الدعم 🎧" value={tb.support} onChange={(v) => setPage("topbar", { ...tb, support: v })} />
        <Toggle label="جرس الإشعارات" value={tb.bell} onChange={(v) => setPage("topbar", { ...tb, bell: v })} />
      </Group>
    </>
  );
}

// ─────────── خارج تلجرام + SEO ───────────
export function LandingPanel({ d, setPage, set, bot }) {
  const p = d.pages.landing;
  const upd = (k) => (v) => setPage("landing", { ...p, [k]: v });
  const seo = d.seo;
  const s = (k) => (v) => set({ ...d, seo: { ...seo, [k]: v } });
  return (
    <>
      <Group title="🌐 صفحة من يفتح الرابط خارج تلجرام" hint={`يظهر رمز QR ورابط t.me/${bot || "…"} لفتح البوت. لا يعمل التطبيق نفسه خارج تلجرام.`}>
        <Text label="العنوان (عربي)" value={p.title_ar} max={60} onChange={upd("title_ar")} />
        <Text label="Title (EN)" value={p.title_en} max={60} dir="ltr" onChange={upd("title_en")} />
        <Text label="الوصف (عربي)" value={p.sub_ar} max={240} area onChange={upd("sub_ar")} />
        <Text label="Description (EN)" value={p.sub_en} max={240} area dir="ltr" onChange={upd("sub_en")} />
        <Text label="نص الزر (عربي)" value={p.button_ar} max={60} onChange={upd("button_ar")} />
        <Text label="Button (EN)" value={p.button_en} max={60} dir="ltr" onChange={upd("button_en")} />
        <Toggle label="رمز QR" value={p.show_qr} onChange={upd("show_qr")} />
        <Toggle label="قائمة الميزات" value={p.show_features} onChange={upd("show_features")} />
      </Group>
      <Group title="🔎 SEO ومعاينة الروابط" hint="يظهر في جوجل ومعاينات الروابط في واتساب/تلجرام/تويتر. يُكتب في صفحة التطبيق فور النشر.">
        <Text label="عنوان الصفحة" value={seo.title} max={70} onChange={s("title")} />
        <Text label="الوصف" value={seo.description} max={170} area onChange={s("description")} />
        <Text label="الكلمات المفتاحية" value={seo.keywords} max={200} onChange={s("keywords")} />
        <Text label="اسم الموقع" value={seo.site_name} max={40} onChange={s("site_name")} />
        <Text label="صورة المعاينة (رابط https)" value={seo.og_image} max={400} dir="ltr" onChange={s("og_image")} />
        <Color label="لون شريط المتصفح" value={seo.theme_color} onChange={s("theme_color")} />
        <Toggle label="السماح لمحركات البحث بالفهرسة" value={seo.index} onChange={s("index")} />
        <div className="st-serp">
          <small className="mono">{(window.location.origin || "").replace(/^https?:\/\//, "")}</small>
          <b>{seo.title || "—"}</b>
          <span>{seo.description || "—"}</span>
        </div>
      </Group>
    </>
  );
}

// ─────────── كل نصوص التطبيق ───────────
export function TextsPanel({ d, set }) {
  const [q, setQ] = useState("");
  const [only, setOnly] = useState(false);
  const keys = useMemo(() => Object.keys(messages.ar).filter((k) => typeof messages.ar[k] === "string" && k !== "dir"), []);
  const shown = keys.filter((k) => {
    const hit = !q || k.toLowerCase().includes(q.toLowerCase()) || messages.ar[k].includes(q) || String(messages.en[k] || "").toLowerCase().includes(q.toLowerCase());
    return hit && (!only || d.texts.ar[k] || d.texts.en[k]);
  }).slice(0, 120);
  const put = (lang, k, v) => set({ ...d, texts: { ...d.texts, [lang]: { ...d.texts[lang], [k]: v } } });
  const count = Object.keys(d.texts.ar).length + Object.keys(d.texts.en).length;
  return (
    <Group title={`✍️ كل نصوص التطبيق (${keys.length} نصًا · ${count} معدّل)`} hint="ابحث بأي كلمة تراها في التطبيق. اترك الحقل فارغًا لاستخدام النص الأصلي. المتغيرات مثل {n} تبقى كما هي.">
      <div className="st-row">
        <input className="search" placeholder="ابحث عن نص… (مثال: الرصيد، اشترك، Balance)" value={q} onChange={(e) => setQ(e.target.value)} />
        <label className="check"><input type="checkbox" checked={only} onChange={(e) => setOnly(e.target.checked)} />المعدّلة فقط</label>
      </div>
      <div className="st-texts">
        {shown.map((k) => (
          <div key={k} className={`st-text-row ${d.texts.ar[k] || d.texts.en[k] ? "is-edited" : ""}`}>
            <code>{k}</code>
            <textarea rows={1} placeholder={messages.ar[k]} value={d.texts.ar[k] || ""} onChange={(e) => put("ar", k, e.target.value)} />
            <textarea rows={1} dir="ltr" placeholder={messages.en[k]} value={d.texts.en[k] || ""} onChange={(e) => put("en", k, e.target.value)} />
          </div>
        ))}
        {shown.length === 120 && <p className="muted">اعرض نتائج أقل بالبحث…</p>}
      </div>
    </Group>
  );
}
