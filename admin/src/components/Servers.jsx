import React, { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";

const TYPE = { demo: "تجريبي", real: "حقيقي", unknown: "غير محدد" };

/** خوادم MT5: السجل الذي تُقترح منه الأسماء على المستخدمين أثناء الربط. */
export default function Servers() {
  const [rows, setRows] = useState(null);
  const [q, setQ] = useState("");
  const [text, setText] = useState("");
  const [msg, setMsg] = useState("");
  const load = useCallback(() => api.servers().then((r) => setRows(r.servers)).catch(() => setRows([])), []);
  useEffect(() => { load(); }, [load]);
  const shown = useMemo(() => (rows || []).filter((r) => (r.name || "").toLowerCase().includes(q.toLowerCase())), [rows, q]);

  async function doImport(t) {
    try {
      const r = await api.importServers(t);
      setMsg(`✅ أُضيف/حُدّث ${r.imported} خادم`);
      setText("");
      load();
    } catch {
      setMsg("❌ ملف غير صالح");
    }
  }

  return (
    <>
      <div className="topbar">
        <h1>خوادم MT5</h1>
        <div className="row-gap">
          {msg && <span className="muted">{msg}</span>}
          <button onClick={() => api.backfillServers().then((r) => { setMsg(`✅ سُجّل ${r.imported} من الحسابات المربوطة`); load(); })}>مزامنة من الحسابات المربوطة</button>
        </div>
      </div>
      <p className="muted">كل ربط ناجح يضيف اسم خادمه تلقائيًا كـ«موثّق». يمكنك أيضًا استيراد قائمة: سطر لكل خادم <code>Name,demo|live</code> أو ملف JSON.</p>

      <div className="panel">
        <h2>استيراد قائمة</h2>
        <textarea className="mono big-text" rows={5} placeholder={"Exness-MT5Trial16,demo\nICMarketsSC-MT5-2,live"} value={text} onChange={(e) => setText(e.target.value)} />
        <div className="row-gap">
          <button className="primary" disabled={!text.trim()} onClick={() => doImport(text)}>استيراد</button>
          <label className="file-btn">من ملف (CSV/JSON)<input type="file" accept=".csv,.json,.txt" hidden onChange={async (e) => e.target.files[0] && doImport(await e.target.files[0].text())} /></label>
        </div>
      </div>

      <div className="panel">
        <div className="topbar">
          <h2>السجل ({rows ? rows.length : "…"})</h2>
          <input className="narrow-wide" placeholder="بحث…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <div className="scrollx">
          <table className="list keep">
            <thead><tr><th>الخادم</th><th>النوع</th><th>الحالة</th><th>ربطات ناجحة</th><th /></tr></thead>
            <tbody>
              {shown.slice(0, 300).map((r) => (
                <tr key={r.id}>
                  <td className="mono">{r.name}</td>
                  <td><span className={`badge ${r.type === "demo" ? "pending" : r.type === "real" ? "approved" : "neutral"}`}>{TYPE[r.type]}</span></td>
                  <td>{r.verified ? "✓ موثّق" : "مستورد"}</td>
                  <td className="mono">{r.links}</td>
                  <td><button className="danger-ghost" onClick={() => api.deleteServer(r.id).then(load)}>حذف</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
