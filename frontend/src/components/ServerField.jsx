import React, { useEffect, useId, useRef, useState } from 'react';
import { searchServers } from '../api';
import { fill } from '../i18n';

/**
 * حقل اسم الخادم مع اقتراحات أثناء الكتابة من سجل الخوادم (أسماء قبلها MT5 فعلًا + قوائم الأدمن).
 * كل اقتراح يوضح Demo/Live، ويُقترح الاسم الصحيح عند وجود خطأ إملائي.
 */
export default function ServerField({ t, value, onChange, error }) {
  const id = useId();
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const [picked, setPicked] = useState(false);
  const timer = useRef(null);

  useEffect(() => {
    clearTimeout(timer.current);
    if (picked || value.trim().length < 2) {
      setItems([]);
      return undefined;
    }
    timer.current = setTimeout(() => {
      searchServers(value.trim()).then((r) => setItems(r.servers || [])).catch(() => setItems([]));
    }, 220);
    return () => clearTimeout(timer.current);
  }, [value, picked]);

  const choose = (s) => {
    onChange(s.name);
    setPicked(true);
    setOpen(false);
  };
  const exact = items.find((s) => s.exact);
  const best = !exact && items[0];
  const badge = (s) => (s.type === 'demo' ? t.srvDemo : s.type === 'real' ? t.srvLive : '');

  return (
    <div className={`field server-field ${error ? 'has-error' : ''}`}>
      <label htmlFor={id}>{t.server}</label>
      <div className="control">
        <input
          id={id}
          dir="ltr"
          value={value}
          placeholder={t.serverPh}
          autoComplete="off"
          autoCapitalize="off"
          autoCorrect="off"
          spellCheck={false}
          role="combobox"
          aria-expanded={open && items.length > 0}
          aria-controls={`${id}-list`}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          onChange={(e) => {
            setPicked(false);
            setOpen(true);
            onChange(e.target.value);
          }}
        />
        {exact && <span className="srv-ok" title={t.srvVerified}>✓</span>}
      </div>

      {open && items.length > 0 && (
        <ul className="srv-list" id={`${id}-list`} role="listbox">
          {items.map((s) => (
            <li key={s.id} role="option" aria-selected={s.exact}>
              <button type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => choose(s)}>
                <bdi dir="ltr" className="srv-name">{s.name}</bdi>
                {badge(s) && <span className={`srv-type is-${s.type}`}>{badge(s)}</span>}
                {s.verified && <span className="srv-verified">{t.srvVerified}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}

      {!open && best && value.trim().length >= 3 && (
        <button type="button" className="srv-dym" onClick={() => choose(best)}>
          {fill(t.srvDidYouMean, { name: '' })}<bdi dir="ltr">{best.name}</bdi>
          {badge(best) && <span className={`srv-type is-${best.type}`}>{badge(best)}</span>}
        </button>
      )}
      {error && <p className="msg error">{error}</p>}
    </div>
  );
}
