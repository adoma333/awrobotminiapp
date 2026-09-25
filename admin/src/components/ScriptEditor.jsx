import React, { useRef, useState } from "react";
import { api } from "../api";

const COLORS = ["#ff8a00", "#1fa7a0", "#e5b84b", "#8b7cf6", "#ef5f7a", "#3ddc97", "#5aa9ff", "#c0c6d0"];

// رسم خطي بسيط بلا مكتبات لسلسلة كل اسم على مدى أسبوع
function Chart({ names, series }) {
  const W = 640, H = 220, P = 28;
  const all = series.flat();
  const max = Math.max(1, ...all), min = Math.min(0, ...all);
  const len = Math.max(...series.map((s) => s.length), 2);
  const x = (i) => P + (i / (len - 1)) * (W - P * 2);
  const y = (v) => H - P - ((v - min) / (max - min || 1)) * (H - P * 2);
  return (
    <div className="script-chart">
      <svg viewBox={`0 0 ${W} ${H}`} direction="ltr" style={{ direction: "ltr" }} role="img" aria-label="معاينة الحركة خلال أسبوع">
        {[0, 0.25, 0.5, 0.75, 1].map((f) => (
          <g key={f}>
            <line x1={P} x2={W - P} y1={y(min + (max - min) * f)} y2={y(min + (max - min) * f)} stroke="currentColor" strokeOpacity=".08" />
            <text x={2} y={y(min + (max - min) * f) + 4} fontSize="9" fill="currentColor" opacity=".5">{Math.round(min + (max - min) * f).toLocaleString("en-US")}</text>
          </g>
        ))}
        {series.map((s, k) => (
          <polyline key={k} fill="none" stroke={COLORS[k % COLORS.length]} strokeWidth="1.8" strokeLinejoin="round"
            points={s.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ")} />
        ))}
      </svg>
      <div className="script-legend">
        {names.map((n, k) => <span key={k}><i style={{ background: COLORS[k % COLORS.length] }} />{n}</span>)}
      </div>
    </div>
  );
}

/** محرر معادلة حركة المتصدرين: لغة آمنة (لا تُنفَّذ كبايثون)، قوالب جاهزة، مساعدة المتغيرات والدوال، ومعاينة أسبوع كامل. */
export default function ScriptEditor({ value, onChange, enabled, onToggle, intervalSec, meta }) {
  const ref = useRef(null);
  const [preview, setPreview] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const lines = Math.max(4, (value || "").split("\n").length);

  function insert(text) {
    const el = ref.current;
    const v = value || "";
    const a = el ? el.selectionStart : v.length, b = el ? el.selectionEnd : v.length;
    onChange(v.slice(0, a) + text + v.slice(b));
    requestAnimationFrame(() => { if (el) { el.focus(); el.selectionStart = el.selectionEnd = a + text.length; } });
  }
  function onKey(e) {
    if (e.key === "Tab") { e.preventDefault(); insert("  "); }
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); run(); }
  }
  async function run() {
    setErr(""); setBusy(true);
    try { setPreview(await api.leaderboardScriptPreview(value, intervalSec)); } catch (e) { setPreview(null); setErr(e.detail || "تعذّرت المعاينة"); } finally { setBusy(false); }
  }

  return (
    <div className="script-editor">
      <label className="check"><input type="checkbox" checked={enabled} onChange={(e) => onToggle(e.target.checked)} /> استخدام معادلة مخصّصة للحركة بدل التذبذب الافتراضي (تعمل عند تفعيل المحاكاة)</label>
      <div className="row-gap">
        <span className="muted">قوالب جاهزة:</span>
        {(meta.presets || []).map((p) => <button key={p.name} type="button" onClick={() => onChange(p.script)}>{p.name}</button>)}
      </div>
      <div className="code-box" dir="ltr">
        <pre className="code-gutter" aria-hidden="true">{Array.from({ length: lines }, (_, i) => i + 1).join("\n")}</pre>
        <textarea ref={ref} className="code-area" dir="ltr" spellCheck={false} rows={lines} value={value || ""} placeholder="cur + noise(base * 0.03) + (base - cur) * 0.2"
          onChange={(e) => onChange(e.target.value)} onKeyDown={onKey} />
      </div>
      <div className="row-gap">
        <button type="button" className="primary" disabled={busy || !(value || "").trim()} onClick={run}>{busy ? "جارٍ المحاكاة…" : "معاينة أسبوع كامل (Ctrl+Enter)"}</button>
        <span className="muted">المعادلة تُحسب لكل اسم في كل حركة وتُرجع ربحه الجديد بالدولار. الحفظ يتحقق منها أولًا.</span>
      </div>
      {err && <p className="error-text mono" dir="auto">✗ {err}</p>}
      {meta.error && !err && <p className="error-text">آخر خطأ أثناء التشغيل: <span className="mono">{meta.error}</span> — الحركة متوقفة مؤقتًا حتى تصحيح المعادلة.</p>}
      {preview && <Chart names={preview.names} series={preview.series} />}
      <div className="two-col">
        <div>
          <h3>المتغيرات (اضغط للإدراج)</h3>
          <div className="chips">
            {Object.entries(meta.vars || {}).map(([k, v]) => <button key={k} type="button" className="chip" title={v} onClick={() => insert(k)}><b className="mono">{k}</b> <span className="muted">{v}</span></button>)}
          </div>
        </div>
        <div>
          <h3>الدوال</h3>
          <div className="chips">
            {["sin", "cos", "abs", "min", "max", "clamp", "floor", "round", "sqrt", "log", "exp"].map((f) => <button key={f} type="button" className="chip" onClick={() => insert(`${f}(`)}><b className="mono" dir="ltr">{f}()</b></button>)}
            {Object.entries(meta.funcs || {}).map(([k, v]) => <button key={k} type="button" className="chip" title={v} onClick={() => insert(k.replace(/\(.*$/, "("))}><b className="mono" dir="ltr">{k}</b> <span className="muted">{v}</span></button>)}
          </div>
          <p className="muted">العمليات: <span className="mono">+ - * / // % ** &lt; &gt; == and or not</span> والشرط <span className="mono">a if شرط else b</span>. للأمان: لا متغيرات ولا دوال خارج هذه القائمة، ولا نصوص أو استيراد.</p>
        </div>
      </div>
    </div>
  );
}
