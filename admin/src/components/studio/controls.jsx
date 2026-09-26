import React, { useState } from "react";
import Icon from "@app/components/Icon.jsx";

// ─────────── عناصر تحكم مشتركة لاستوديو التصميم ───────────
export function Color({ label, value, onChange }) {
  return (
    <label className="st-color">
      <span>{label}</span>
      <span className="st-color-in">
        <input type="color" value={value} onChange={(e) => onChange(e.target.value)} />
        <input className="mono" value={value} maxLength={7} onChange={(e) => /^#[0-9a-fA-F]{0,6}$/.test(e.target.value) && e.target.value.length === 7 && onChange(e.target.value)} />
      </span>
    </label>
  );
}

export function Range({ label, value, min, max, step = 1, unit = "", onChange }) {
  return (
    <label className="st-range">
      <span>{label} <b className="mono">{value}{unit}</b></span>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} />
    </label>
  );
}

export function Seg({ label, value, options, onChange }) {
  return (
    <div className="st-seg">
      {label && <span>{label}</span>}
      <div className="st-seg-row">
        {options.map(([v, l]) => (
          <button key={v} type="button" className={value === v ? "on" : ""} onClick={() => onChange(v)}>{l}</button>
        ))}
      </div>
    </div>
  );
}

export function Toggle({ label, value, onChange, hint }) {
  return (
    <label className="st-toggle">
      <input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} />
      <span className="st-switch" />
      <span>{label}{hint && <small>{hint}</small>}</span>
    </label>
  );
}

export function Text({ label, value, onChange, max = 240, area = false, dir }) {
  return (
    <label className="st-text">
      <span>{label} <small className="muted">{(value || "").length}/{max}</small></span>
      {area
        ? <textarea rows={3} maxLength={max} value={value || ""} dir={dir || "auto"} onChange={(e) => onChange(e.target.value)} />
        : <input maxLength={max} value={value || ""} dir={dir || "auto"} onChange={(e) => onChange(e.target.value)} />}
    </label>
  );
}

/** منتقي أيقونات بشبكة + بحث + رأي الذكاء الاصطناعي (اقتراح وبدائل وتطبيق بنقرة). */
export function IconPicker({ value, icons, label, onChange, askAi }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [ai, setAi] = useState(null);
  const [busy, setBusy] = useState(false);
  async function ask() {
    setBusy(true);
    setAi(null);
    try { setAi(await askAi(label, value)); } catch (e) { setAi({ error: e.detail || "تعذّر الحصول على رأي الذكاء" }); } finally { setBusy(false); }
  }
  return (
    <div className="st-icon">
      <button type="button" className="st-icon-btn" onClick={() => setOpen(!open)} title="تغيير الأيقونة">
        <Icon name={value} size={20} /><span className="mono">{value}</span>
      </button>
      {open && (
        <div className="st-icon-pop">
          <div className="st-icon-top">
            <input placeholder="بحث…" value={q} onChange={(e) => setQ(e.target.value)} />
            {askAi && <button type="button" className="st-ai-btn" disabled={busy} onClick={ask}>{busy ? "…" : "✨ رأي الذكاء"}</button>}
          </div>
          {ai && !ai.error && (
            <div className="st-ai-icon">
              <span>✨ يقترح: </span>
              {[ai.icon, ...(ai.alternatives || [])].map((n) => (
                <button key={n} type="button" className={n === ai.icon ? "best" : ""} onClick={() => { onChange(n); setOpen(false); }} title={n}><Icon name={n} size={20} /></button>
              ))}
              <small>{ai.reason}</small>
            </div>
          )}
          {ai?.error && <p className="error-text">{ai.error}</p>}
          <div className="st-icon-grid">
            {icons.filter((n) => !q || n.includes(q.toLowerCase())).map((n) => (
              <button key={n} type="button" className={n === value ? "on" : ""} onClick={() => { onChange(n); setOpen(false); }} title={n}>
                <Icon name={n} size={20} />
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/** قائمة قابلة للسحب والإفلات (مع أزرار ↑↓ للشاشات اللمسية). */
export function DragList({ items, render, onChange, keyOf = (x) => x.id }) {
  const [drag, setDrag] = useState(null);
  const [over, setOver] = useState(null);
  const move = (from, to) => {
    if (from === to || to < 0 || to >= items.length) return;
    const next = [...items];
    const [x] = next.splice(from, 1);
    next.splice(to, 0, x);
    onChange(next);
  };
  return (
    <ul className="st-drag">
      {items.map((it, i) => (
        <li key={keyOf(it)} draggable
          className={`${drag === i ? "is-drag" : ""} ${over === i && drag !== i ? "is-over" : ""}`}
          onDragStart={(e) => { setDrag(i); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", String(i)); }}
          onDragOver={(e) => { e.preventDefault(); setOver(i); }}
          onDragLeave={() => setOver(null)}
          onDrop={(e) => { e.preventDefault(); move(drag ?? Number(e.dataTransfer.getData("text/plain")), i); setDrag(null); setOver(null); }}
          onDragEnd={() => { setDrag(null); setOver(null); }}>
          <span className="st-grip" aria-hidden="true">⋮⋮</span>
          <div className="st-drag-body">{render(it, i)}</div>
          <span className="st-arrows">
            <button type="button" disabled={i === 0} onClick={() => move(i, i - 1)} aria-label="للأعلى">↑</button>
            <button type="button" disabled={i === items.length - 1} onClick={() => move(i, i + 1)} aria-label="للأسفل">↓</button>
          </span>
        </li>
      ))}
    </ul>
  );
}

export function Group({ title, children, open: initial = true, hint }) {
  const [open, setOpen] = useState(initial);
  return (
    <section className={`st-group ${open ? "open" : ""}`}>
      <button type="button" className="st-group-head" onClick={() => setOpen(!open)}>
        <span>{title}</span><i>{open ? "−" : "+"}</i>
      </button>
      {open && <div className="st-group-body">{hint && <p className="muted st-hint">{hint}</p>}{children}</div>}
    </section>
  );
}
