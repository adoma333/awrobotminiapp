import React, { useEffect, useRef, useState } from "react";

const APP_URL = import.meta.env.VITE_APP_PREVIEW_URL || "/";

/**
 * يعرض التطبيق الحقيقي (وضع المعاينة ?preview=1 ببيانات وهمية) داخل إطار جهاز بمقاسه الفعلي،
 * ويرسل له تصميم المسودة والصفحة والوضع واللغة لحظيًا عبر postMessage.
 */
export default function DevicePreview({ device, design, view, theme, lang, scale = 1, landscape = false, label = true }) {
  const ref = useRef(null);
  const [ready, setReady] = useState(false);
  const target = new URL(APP_URL, window.location.href).origin;
  const w = landscape ? device.h : device.w;
  const h = landscape ? device.w : device.h;

  const send = (msg) => ref.current?.contentWindow?.postMessage(msg, target);
  useEffect(() => {
    const onMsg = (e) => {
      if (e.source === ref.current?.contentWindow && e.data?.type === "aw-preview-ready") setReady(true);
    };
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
  }, []);
  useEffect(() => { if (ready) send({ type: "aw-design", design }); }, [ready, design]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (ready) { send({ type: "aw-theme", theme }); send({ type: "aw-lang", lang }); } }, [ready, theme, lang]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (ready) send({ type: "aw-view", view }); }, [ready, view]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="dp-wrap" style={{ width: (w + 24) * scale, height: (h + 24) * scale + (label ? 26 : 0) }}>
      <div className={`dp-frame cut-${device.cut}`} style={{ width: w + 24, height: h + 24, borderRadius: device.r + 12, transform: `scale(${scale})` }}>
        <div className="dp-screen" style={{ width: w, height: h, borderRadius: device.r }}>
          {device.cut === "window" && <div className="dp-titlebar"><i /><i /><i /><span>AW ROBOT</span></div>}
          <iframe ref={ref} title={device.name} src={`${APP_URL}?preview=1&d=${device.id}`} style={{ width: w, height: device.cut === "window" ? h - 26 : h }} />
          {!ready && <div className="dp-loading">…</div>}
        </div>
      </div>
      {label && <div className="dp-label" style={{ top: (h + 24) * scale + 4 }}>{device.name} · <span className="mono">{w}×{h}</span></div>}
    </div>
  );
}
