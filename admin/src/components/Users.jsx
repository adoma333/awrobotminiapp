import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import UserDetail from "./UserDetail";

const TABS = [
  { key: "approved", label: "مربوط" },
  { key: "pending", label: "قيد المراجعة" },
  { key: "rejected", label: "مرفوض" },
  { key: "", label: "الكل" },
];

function fmtMoney(v, cur) {
  if (v === null || v === undefined) return "—";
  return `${Number(v).toLocaleString("en-US", { maximumFractionDigits: 2 })} ${cur || ""}`.trim();
}
function timeAgo(epoch) {
  if (!epoch) return "—";
  const diff = Date.now() / 1000 - epoch;
  if (diff < 60) return "الآن";
  if (diff < 3600) return `منذ ${Math.floor(diff / 60)} د`;
  if (diff < 86400) return `منذ ${Math.floor(diff / 3600)} س`;
  return `منذ ${Math.floor(diff / 86400)} يوم`;
}


/** المستخدمون: البحث والفلترة، القائمة (جدول على الحاسوب وبطاقات على الجوال)، وتفاصيل كل مستخدم. */
export default function Users({ canWrite }) {
  const [stats, setStats] = useState(null);
  const [tab, setTab] = useState("approved");
  const [accountType, setAccountType] = useState("");
  const [levMin, setLevMin] = useState("");
  const [levMax, setLevMax] = useState("");
  const [search, setSearch] = useState("");
  const [users, setUsers] = useState(null);
  const [error, setError] = useState("");
  const [openId, setOpenId] = useState(null);

  const loadStats = useCallback(() => {
    api.stats().then(setStats).catch(() => {});
  }, []);

  const loadUsers = useCallback(() => {
    setError("");
    api
      .users({
        status: tab || undefined,
        account_type: accountType || undefined,
        leverage_min: levMin || undefined,
        leverage_max: levMax || undefined,
        search: search || undefined,
      })
      .then((r) => setUsers(r.users))
      .catch(() => setError("تعذّر تحميل القائمة. تحقّق من الاتصال وحاول مجددًا."));
  }, [tab, accountType, levMin, levMax, search]);

  useEffect(loadStats, [loadStats]);
  useEffect(() => {
    const t = setTimeout(loadUsers, 250);
    return () => clearTimeout(t);
  }, [loadUsers]);

  function handleDecided(id) {
    setUsers((prev) => (prev ? prev.filter((u) => u.id !== id) : prev));
    loadStats();
  }

  const statusLabel = { pending: "قيد المراجعة", approved: "مربوط", rejected: "مرفوض", unlinked: "فكّ الربط" };

  return (
    <>
        <div className="topbar">
          <h1>المستخدمون</h1>
        </div>
        <div className="tabs page-tabs">
          {TABS.map((t) => (
            <button key={t.key} className={`tab ${tab === t.key ? "active" : ""}`} onClick={() => setTab(t.key)}>
              {t.label}
              {stats && t.key && <span className="count mono">{stats[t.key] ?? ""}</span>}
            </button>
          ))}
        </div>

        {stats && (
          <div className="stat-row">
            <div className="stat"><b>{stats.pending}</b><span>قيد المراجعة</span></div>
            <div className="stat"><b>{stats.approved}</b><span>مقبول</span></div>
            <div className="stat"><b>{stats.rejected}</b><span>مرفوض</span></div>
          </div>
        )}

        <div className="filters">
          <input
            className="search"
            placeholder="بحث بالاسم أو اليوزر أو رقم الحساب…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <select value={accountType} onChange={(e) => setAccountType(e.target.value)}>
            <option value="">كل الحسابات</option>
            <option value="real">حقيقي</option>
            <option value="demo">تجريبي</option>
          </select>
          <input className="lev" inputMode="numeric" placeholder="رافعة من" value={levMin} onChange={(e) => setLevMin(e.target.value.replace(/\D/g, ""))} />
          <input className="lev" inputMode="numeric" placeholder="إلى" value={levMax} onChange={(e) => setLevMax(e.target.value.replace(/\D/g, ""))} />
        </div>

        {error && <p style={{ color: "var(--bad)" }}>{error}</p>}

        {users && users.length === 0 && !error && (
          <div className="empty">لا توجد طلبات مطابقة لهذا الفلتر حاليًا.</div>
        )}

        {users && users.length > 0 && (
          <>
            <div className="scrollx">
              <table className="list">
                <thead>
                  <tr>
                    <th>المستخدم</th>
                    <th>الحساب</th>
                    <th>النوع</th>
                    <th>الرافعة</th>
                    <th>الرصيد</th>
                    <th>الحالة</th>
                    <th>منذ</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((u) => (
                    <tr key={u.id} onClick={() => setOpenId(u.id)}>
                      <td>{u.nickname || u.username || u.id}</td>
                      <td className="mono">{u.mt5_login}</td>
                      <td>{u.account_type === "real" ? "حقيقي" : u.account_type === "demo" ? "تجريبي" : "—"}</td>
                      <td className="mono">{u.leverage ? `1:${u.leverage}` : "—"}</td>
                      <td className="mono">{fmtMoney(u.balance, u.currency)}</td>
                      <td><span className={`badge ${u.status}`}>{statusLabel[u.status] || u.status}</span></td>
                      <td className="mono">{timeAgo(u.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="cardlist">
              {users.map((u) => (
                <div className="ucard" key={u.id} onClick={() => setOpenId(u.id)}>
                  <div className="row1">
                    <span className="name">{u.nickname || u.username || u.id}</span>
                    <span className={`badge ${u.status}`}>{statusLabel[u.status] || u.status}</span>
                  </div>
                  <div className="meta">
                    <span className="mono">{u.mt5_login}</span>
                    <span>{u.account_type === "real" ? "حقيقي" : u.account_type === "demo" ? "تجريبي" : "—"}</span>
                    {u.leverage ? <span className="mono">1:{u.leverage}</span> : null}
                    <span className="mono">{fmtMoney(u.balance, u.currency)}</span>
                    <span>{timeAgo(u.created_at)}</span>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}

      {openId && <UserDetail id={openId} canWrite={canWrite} onClose={() => setOpenId(null)} onDecided={handleDecided} />}
    </>
  );
}
