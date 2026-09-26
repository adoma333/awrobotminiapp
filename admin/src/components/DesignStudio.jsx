import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import DevicePreview from "./studio/DevicePreview";
import { DEVICES, DEVICE_GROUPS, byId } from "./studio/devices";
import { GlobalPanel, HomePanel, LandingPanel, NavPanel, StartPanel, TextsPanel } from "./studio/Inspector";
import { Group } from "./studio/controls";

const PAGES = [
  ["global", "🎨 الهوية العامة", "home"], ["start", "🚀 صفحة البداية", "start"], ["home", "🏠 الرئيسية", "home"],
  ["nav", "📌 الشريطان العلوي والسفلي", "home"], ["landing", "🌐 خارج تلجرام + SEO", "landing"], ["texts", "✍️ كل النصوص", "home"],
];
const VIEWS = [["home", "الرئيسية"], ["start", "صفحة البداية"], ["landing", "خارج تلجرام"], ["analytics", "التحليلات"], ["plans", "الباقات"],
  ["rewards", "المكافآت"], ["referral", "الإحالة"], ["settings", "الإعدادات"]];
const SCOPE_LABEL = { global: "الهوية العامة", start: "البداية", home: "الرئيسية", nav: "الشريط السفلي", topbar: "الشريط العلوي", landing: "خارج تلجرام" };
const when = (ts) => (ts ? new Date(ts * 1000).toLocaleString("ar-u-nu-latn", { dateStyle: "short", timeStyle: "short" }) : "—");
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

/** استوديو التصميم: تخصيص كامل لكل صفحات التطبيق مع معاينة حية على أجهزة حقيقية المقاس. */
export default function DesignStudio({ canWrite }) {
  const [st, setSt] = useState(null);
  const [d, setD] = useState(null);
  const [undo, setUndo] = useState([]);
  const [redo, setRedo] = useState([]);
  const [page, setPage] = useState("home");
  const [side, setSide] = useState("edit");
  const [msg, setMsg] = useState("");
  const [saving, setSaving] = useState(false);
  const [dev, setDev] = useState("iphone_15");
  const [multi, setMulti] = useState(false);
  const [theme, setTheme] = useState("dark");
  const [lang, setLang] = useState("ar");
  const [view, setView] = useState("home");
  const [land, setLand] = useState(false);
  const [zoom, setZoom] = useState(0.7);
  const [pv, setPv] = useState(null); // معاينة مؤقتة (إصدار من السجل / اقتراح الذكاء) دون حفظ
  const saveTimer = useRef(null);

  useEffect(() => {
    api.design().then((r) => { setSt(r); setD(r.draft); }).catch(() => setMsg("✗ تعذّر تحميل التصميم"));
  }, []);

  const change = useCallback((next) => {
    setD((cur) => {
      setUndo((u) => [...u.slice(-49), cur]);
      setRedo([]);
      return next;
    });
    setPv(null);
  }, []);

  // حفظ المسودة تلقائيًا (لا يراها المستخدمون حتى النشر)
  useEffect(() => {
    if (!d || !st || !canWrite || same(d, st.draft)) return undefined;
    clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      api.saveDesignDraft(d).then((r) => { setSt((s) => ({ ...s, draft: r.draft })); setMsg("✓ حُفظت المسودة"); })
        .catch((e) => setMsg(`✗ ${e.detail || "تعذّر حفظ المسودة"}`));
    }, 1200);
    return () => clearTimeout(saveTimer.current);
  }, [d]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const onKey = (e) => {
      if (!(e.ctrlKey || e.metaKey) || e.target.closest("input,textarea")) return;
      if (e.key.toLowerCase() === "z" && !e.shiftKey && undo.length) { e.preventDefault(); doUndo(); }
      if ((e.key.toLowerCase() === "y" || (e.key.toLowerCase() === "z" && e.shiftKey)) && redo.length) { e.preventDefault(); doRedo(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  function doUndo() {
    if (!undo.length) return;
    setRedo((r) => [...r, d]);
    setD(undo[undo.length - 1]);
    setUndo((u) => u.slice(0, -1));
  }
  function doRedo() {
    if (!redo.length) return;
    setUndo((u) => [...u, d]);
    setD(redo[redo.length - 1]);
    setRedo((r) => r.slice(0, -1));
  }

  async function publish(design = d, note = "") {
    const n = note || window.prompt("وصف قصير لهذا التحديث (يظهر في السجل):", "") || "";
    setSaving(true);
    try {
      const r = await api.publishDesign(design, n);
      setSt((s) => ({ ...s, published: r.published, draft: r.published, version: r.version }));
      setD(r.published);
      setPv(null);
      setMsg(`✓ نُشر الإصدار ${r.version} — يظهر للمستخدمين خلال 30 ثانية`);
    } catch (e) {
      setMsg(`✗ ${e.detail || "فشل النشر"}`);
    } finally { setSaving(false); }
  }

  const askIcon = useCallback((label, current) => api.designAiIcon(label, current), []);
  const setPageData = useCallback((key, value) => change({ ...d, pages: { ...d.pages, [key]: value } }), [d, change]);
  const shown = pv || d;
  const dirty = st && d && !same(d, st.published);
  const device = byId(dev);
  const multiDevices = useMemo(() => ["iphone_se", "iphone_15", "galaxy_s24", "pixel_8", "iphone_16promax"].map(byId), []);

  if (!d || !st) return <p className="muted">{msg || "جارٍ تحميل استوديو التصميم…"}</p>;
  const cat = st.catalog;
  const panelProps = { d, set: change, setPage: setPageData, icons: cat.icons, catalog: cat, askAi: askIcon, bot: st.bot_username };

  return (
    <div className="studio">
      <div className="studio-bar">
        <h1>استوديو التصميم</h1>
        <span className={`badge ${dirty ? "pending" : "approved"}`}>{dirty ? "تعديلات غير منشورة" : `منشور · الإصدار ${st.version}`}</span>
        <div className="studio-actions">
          <button disabled={!undo.length} onClick={doUndo} title="تراجع (Ctrl+Z)">↶ تراجع</button>
          <button disabled={!redo.length} onClick={doRedo} title="إعادة (Ctrl+Y)">↷ إعادة</button>
          {canWrite && <button disabled={!dirty} onClick={() => change(st.published)}>تجاهل التعديلات</button>}
          {canWrite && <button className="primary" disabled={saving || !dirty} onClick={() => publish()}>{saving ? "…" : "🚀 نشر للمستخدمين"}</button>}
        </div>
      </div>
      {msg && <p className={msg.startsWith("✗") ? "error-text" : "muted"}>{msg}</p>}

      <div className="studio-grid">
        {/* ── اللوحة الجانبية: الصفحات والتحكمات ── */}
        <aside className="studio-side">
          <div className="tabs studio-tabs">
            {[["edit", "✏️ التعديل"], ["themes", "🎭 القوالب"], ["ai", "✨ الذكاء"], ["history", "🕘 السجل"], ["help", "❔ كيف تعمل"]].map(([k, l]) => (
              <button key={k} className={`tab ${side === k ? "active" : ""}`} onClick={() => setSide(k)}>{l}</button>
            ))}
          </div>
          {side === "edit" && (
            <>
              <div className="studio-pages">
                {PAGES.map(([k, l, v]) => (
                  <button key={k} className={page === k ? "on" : ""} onClick={() => { setPage(k); setView(v); }}>{l}</button>
                ))}
              </div>
              <fieldset disabled={!canWrite} className="studio-fields">
                {page === "global" && <GlobalPanel {...panelProps} />}
                {page === "start" && <StartPanel {...panelProps} />}
                {page === "home" && <HomePanel {...panelProps} />}
                {page === "nav" && <NavPanel {...panelProps} />}
                {page === "landing" && <LandingPanel {...panelProps} />}
                {page === "texts" && <TextsPanel {...panelProps} />}
              </fieldset>
            </>
          )}
          {side === "themes" && <Themes st={st} canWrite={canWrite} onDraft={(dr) => change(dr)} />}
          {side === "ai" && <AiPanel d={d} page={page} canWrite={canWrite} onPreview={setPv} onApply={(design, note) => publish(design, note)} />}
          {side === "history" && <History canWrite={canWrite} onPreview={setPv} onRestored={(r) => { setSt((s) => ({ ...s, published: r.published, draft: r.published, version: r.version })); setD(r.published); setPv(null); setMsg(`✓ تم الرجوع — الإصدار ${r.version}`); }} />}
          {side === "help" && <StudioHelp />}
        </aside>

        {/* ── المعاينة الحية ── */}
        <section className="studio-stage">
          <div className="studio-tools">
            <select value={dev} onChange={(e) => setDev(e.target.value)} disabled={multi}>
              {DEVICE_GROUPS.map((g) => (
                <optgroup key={g} label={g}>{DEVICES.filter((x) => x.group === g).map((x) => <option key={x.id} value={x.id}>{x.name} · {x.w}×{x.h}</option>)}</optgroup>
              ))}
            </select>
            <select value={view} onChange={(e) => setView(e.target.value)}>{VIEWS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
            <div className="tabs">
              <button className={`tab ${theme === "dark" ? "active" : ""}`} onClick={() => setTheme("dark")}>🌙</button>
              <button className={`tab ${theme === "light" ? "active" : ""}`} onClick={() => setTheme("light")}>☀️</button>
            </div>
            <div className="tabs">
              <button className={`tab ${lang === "ar" ? "active" : ""}`} onClick={() => setLang("ar")}>ع</button>
              <button className={`tab ${lang === "en" ? "active" : ""}`} onClick={() => setLang("en")}>EN</button>
            </div>
            <button className={multi ? "primary" : ""} onClick={() => setMulti(!multi)} title="عرض عدة أجهزة معًا">▦ عدة أجهزة</button>
            {!multi && <button onClick={() => setLand(!land)} title="تدوير">⟲ {land ? "أفقي" : "عمودي"}</button>}
            <label className="studio-zoom">🔍<input type="range" min={0.35} max={1} step={0.05} value={zoom} onChange={(e) => setZoom(Number(e.target.value))} /></label>
          </div>
          {pv && <div className="studio-pv-note">👁 تعرض معاينة مؤقتة (لم تُطبَّق). <button onClick={() => setPv(null)}>إلغاء المعاينة</button></div>}
          <div className={`studio-devices ${multi ? "is-multi" : ""}`}>
            {multi
              ? multiDevices.map((x) => <DevicePreview key={x.id} device={x} design={shown} view={view} theme={theme} lang={lang} scale={zoom * 0.72} />)
              : <DevicePreview key={dev + land} device={device} design={shown} view={view} theme={theme} lang={lang} scale={zoom} landscape={land} />}
          </div>
        </section>
      </div>
    </div>
  );
}

// ─────────── القوالب: جاهزة + محفوظة (لصفحة أو مجموعة صفحات) ───────────
function Themes({ st, canWrite, onDraft }) {
  const [rows, setRows] = useState([]);
  const [name, setName] = useState("");
  const [tag, setTag] = useState("");
  const [scopes, setScopes] = useState(["global", "home"]);
  const [msg, setMsg] = useState("");
  const load = () => api.designThemes().then((r) => setRows(r.rows)).catch(() => {});
  useEffect(() => { load(); }, []);
  const presets = st.catalog.presets;
  const run = async (fn, ok) => { setMsg(""); try { const r = await fn(); if (r?.draft) onDraft(r.draft); setMsg(ok); load(); } catch (e) { setMsg(`✗ ${e.detail || "فشل"}`); } };
  return (
    <>
      <Group title="🎭 قوالب جاهزة" hint="تُطبَّق على المسودة فقط — راجعها في المعاينة ثم انشر.">
        <div className="st-presets">
          {Object.entries(presets).map(([k, p]) => (
            <button key={k} type="button" disabled={!canWrite} onClick={() => run(() => api.applyDesignPreset(k), `✓ طُبّق «${p.name}» على المسودة`)}>
              <b>{p.name}</b><small>{p.desc}</small>
            </button>
          ))}
        </div>
      </Group>
      {canWrite && (
        <Group title="💾 حفظ التصميم الحالي كقالب" hint="اختر صفحة واحدة أو عدة صفحات لتجميعها في قالب واحد (مجموعة قوالب).">
          <input placeholder="اسم القالب (مثال: رمضان 2026)" value={name} maxLength={60} onChange={(e) => setName(e.target.value)} />
          <input placeholder="وسم اختياري (موسمي، حملة…)" value={tag} maxLength={30} onChange={(e) => setTag(e.target.value)} />
          <div className="st-chips">
            {Object.entries(SCOPE_LABEL).map(([k, l]) => (
              <button key={k} type="button" className={scopes.includes(k) ? "on" : ""} onClick={() => setScopes(scopes.includes(k) ? scopes.filter((x) => x !== k) : [...scopes, k])}>{scopes.includes(k) ? "✓ " : ""}{l}</button>
            ))}
          </div>
          <button className="primary" disabled={!name.trim() || !scopes.length} onClick={() => run(() => api.saveDesignTheme(name.trim(), scopes, tag), "✓ حُفظ القالب").then(() => setName(""))}>حفظ القالب</button>
        </Group>
      )}
      {msg && <p className={msg.startsWith("✗") ? "error-text" : "muted"}>{msg}</p>}
      <Group title={`📚 قوالبي (${rows.length})`}>
        {rows.length === 0 && <p className="muted">لا قوالب محفوظة بعد.</p>}
        {rows.map((r) => (
          <div key={r.id} className="st-theme">
            <div><b>{r.name}</b>{r.tag && <span className="badge neutral">{r.tag}</span>}<small className="muted"> · {when(r.at)}</small></div>
            <div className="st-chips">
              {r.scopes.map((s) => <button key={s} type="button" disabled={!canWrite} title="تطبيق هذه الصفحة فقط" onClick={() => run(() => api.applyDesignTheme(r.id, [s]), `✓ طُبّقت «${SCOPE_LABEL[s]}» من القالب`)}>{SCOPE_LABEL[s]}</button>)}
            </div>
            {canWrite && (
              <div className="row-gap">
                <button className="primary" onClick={() => run(() => api.applyDesignTheme(r.id, null), "✓ طُبّق القالب كاملًا على المسودة")}>تطبيق الكل</button>
                <button className="danger-ghost" onClick={() => window.confirm("حذف القالب؟") && run(() => api.deleteDesignTheme(r.id), "✓ حُذف")}>حذف</button>
              </div>
            )}
          </div>
        ))}
      </Group>
    </>
  );
}

// ─────────── اقتراحات الذكاء الاصطناعي ───────────
const AI_PROMPTS = ["اجعل الواجهة أفخم وأكثر احترافية", "حسّن التباين وسهولة القراءة", "رتّب عناصر الرئيسية حسب الأهمية للمتداول", "اقترح ألوانًا تناسب رمضان", "أزل التكرار واجعل الصفحة أنظف"];

function AiPanel({ d, page, canWrite, onPreview, onApply }) {
  const [scope, setScope] = useState(["global", "start", "home", "nav", "landing"].includes(page) ? page : "global");
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState(null);
  const [err, setErr] = useState("");
  async function ask(text) {
    setBusy(true); setErr(""); setRes(null);
    try {
      const r = await api.designAi(scope, text ?? q, d);
      setRes(r);
      onPreview(r.preview);
    } catch (e) {
      setErr(e.detail === "ai_not_configured" ? "أضف مفتاح Gemini أولًا من الدعم الفني ← الإعدادات." : e.detail || "تعذّر الحصول على اقتراح");
    } finally { setBusy(false); }
  }
  return (
    <>
      <Group title="✨ مساعد التصميم الذكي" hint="يقترح تحسينًا متكاملًا ويعرضه فورًا في المعاينة. «تطبيق الآن» ينشره، ويمكنك الرجوع عنه من السجل في أي وقت.">
        <select value={scope} onChange={(e) => setScope(e.target.value)}>{Object.entries(SCOPE_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
        <textarea rows={3} placeholder="ماذا تريد؟ (مثال: اجعل الرئيسية أبسط وأبرز الرصيد)" value={q} maxLength={600} onChange={(e) => setQ(e.target.value)} />
        <div className="st-chips">{AI_PROMPTS.map((p) => <button key={p} type="button" disabled={busy} onClick={() => { setQ(p); ask(p); }}>{p}</button>)}</div>
        <button className="primary" disabled={busy} onClick={() => ask()}>{busy ? "يفكّر…" : "اطلب اقتراحًا"}</button>
        {err && <p className="error-text">{err}</p>}
        {res && (
          <div className="st-ai-res">
            <p>✨ {res.explanation}</p>
            <pre className="mono">{JSON.stringify(res.patch, null, 1).slice(0, 900)}</pre>
            <div className="row-gap">
              {canWrite && <button className="primary" onClick={() => onApply(res.preview, `اقتراح الذكاء: ${res.explanation.slice(0, 120)}`)}>✓ تطبيق الآن</button>}
              <button onClick={() => { setRes(null); onPreview(null); }}>تجاهل</button>
            </div>
          </div>
        )}
      </Group>
    </>
  );
}

// ─────────── سجل التحديثات: معاينة أي إصدار والرجوع إليه ───────────
function History({ canWrite, onPreview, onRestored }) {
  const [rows, setRows] = useState(null);
  const load = () => api.designHistory().then((r) => setRows(r.rows)).catch(() => setRows([]));
  useEffect(() => { load(); }, []);
  const SRC = { manual: "يدوي", restore: "استرجاع", ai: "ذكاء" };
  return (
    <Group title="🕘 سجل التحديثات" hint="كل نشر يُحفظ هنا. «معاينة» تعرض الإصدار دون تغيير شيء، و«الرجوع» ينشره من جديد (ويمكن التراجع عنه أيضًا).">
      {!rows ? <p className="muted">…</p> : rows.length === 0 ? <p className="muted">لم يُنشر أي تصميم بعد.</p> : rows.map((r) => (
        <div key={r.id} className="st-hist">
          <div><b>الإصدار {r.version}</b> <small className="muted">{when(r.at)} · {SRC[r.source] || r.source} · {r.by}</small></div>
          {r.note && <span>{r.note}</span>}
          <div className="row-gap">
            <button onClick={() => api.designHistoryItem(r.id).then((h) => onPreview(h.data))}>👁 معاينة</button>
            {canWrite && <button onClick={() => window.confirm(`الرجوع للإصدار ${r.version}؟`) && api.restoreDesign(r.id).then((x) => { onRestored(x); load(); })}>↩ الرجوع لهذا الإصدار</button>}
          </div>
        </div>
      ))}
    </Group>
  );
}

function StudioHelp() {
  return (
    <div className="st-help">
      <Group title="كيف يعمل استوديو التصميم؟">
        <ol>
          <li><b>اختر الصفحة</b> من «التعديل» (الهوية العامة، البداية، الرئيسية، الشريطين، خارج تلجرام، النصوص).</li>
          <li><b>عدّل</b>: كل تغيير يظهر فورًا في المعاينة على الجهاز المختار، ويُحفظ كمسودة تلقائيًا.</li>
          <li><b>اسحب وأفلت</b> العناصر لترتيبها (أو استخدم ↑↓)، وأزل العلامة لإخفاء أي عنصر.</li>
          <li><b>جرّب على أجهزة متعددة</b>: اختر أي آيفون أو أندرويد أو تابلت، أو «عدة أجهزة» لرؤية 5 أجهزة معًا، بالليلي والنهاري وبالعربية والإنجليزية.</li>
          <li><b>انشر</b>: المستخدمون لا يرون شيئًا حتى تضغط «نشر للمستخدمين». يصلهم خلال 30 ثانية.</li>
          <li><b>تراجع بأمان</b>: Ctrl+Z داخل الجلسة، و«السجل» للرجوع لأي إصدار منشور سابق.</li>
        </ol>
      </Group>
      <Group title="القوالب" open={false}><p>القوالب الجاهزة نقطة بداية سريعة. «حفظ كقالب» يحفظ صفحة أو عدة صفحات معًا لتعيد استخدامها لاحقًا (مثل تصميم لكل موسم أو حملة)، ويمكن تطبيق صفحة واحدة من القالب فقط.</p></Group>
      <Group title="الذكاء الاصطناعي" open={false}><p>اطلب ما تريد بلغتك؛ يُعرض الاقتراح في المعاينة مع شرحه. «تطبيق الآن» ينشره مع ملاحظة في السجل. في منتقي الأيقونات زر «رأي الذكاء» يقترح أنسب أيقونة وبدائلها.</p></Group>
      <Group title="الأمان" open={false}><p>كل قيمة يتحقق منها الخادم (ألوان وقوائم ونطاقات محددة فقط)، فلا يمكن كسر التطبيق أو حقن أكواد من الاستوديو.</p></Group>
    </div>
  );
}
