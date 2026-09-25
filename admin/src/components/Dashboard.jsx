import React, { useEffect, useState } from "react";
import logo from "../assets/logo-wordmark.png";
import Ceo from "./Ceo";
import Users from "./Users";
import Rewards from "./Rewards";
import Packages from "./Packages";
import LeaderboardSettings from "./LeaderboardSettings";
import AppSettings from "./AppSettings";
import Servers from "./Servers";
import Staff from "./Staff";
import Audit from "./Audit";
import SystemStatus from "./SystemStatus";
import Support from "./Support";
import Notifications from "./Notifications";
import Announcements from "./Announcements";
import TonWallet from "./TonWallet";
import Alerts from "./Alerts";
import "../dashboard.css";

const I = {
  ceo: "M4 20V10M10 20V4M16 20v-7M22 20H2",
  users: "M16 20v-1.5a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4V20M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8M22 20v-1.5a4 4 0 0 0-3-3.8M16 3.2a4 4 0 0 1 0 7.6",
  packages: "M6 3h12l3 5-9 13L3 8ZM3 8h18",
  rewards: "M3.5 8h17v5h-17ZM5 13v7h14v-7M12 8v12M12 8c-1.5-3.5-5.5-3.5-5.5-1 0 1.5 2.5 1 5.5 1ZM12 8c1.5-3.5 5.5-3.5 5.5-1 0 1.5-2.5 1-5.5 1Z",
  leaderboard: "M8 21h8M12 17v4M7 4h10v5a5 5 0 0 1-10 0ZM17 5h3a3 3 0 0 1-3 4M7 5H4a3 3 0 0 0 3 4",
  control: "M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6",
  servers: "M3 3h18v7H3ZM3 14h18v7H3ZM7 6.5h.01M7 17.5h.01",
  staff: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8M4 21a8 8 0 0 1 16 0",
  audit: "M9 5H5v16h14V5h-4M9 3h6v4H9ZM8 12h8M8 16h5",
  system: "M22 12h-4l-3 9L9 3l-3 9H2",
  support: "M4 14v-2a8 8 0 0 1 16 0v2M3 13.5h4V20H3ZM17 13.5h4V20h-4ZM19 20a3.5 3.5 0 0 1-3.5 2H13",
  notifications: "M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15ZM10 20.5a2.2 2.2 0 0 0 4 0",
  announcements: "M4 10v4a1 1 0 0 0 1 1h2l6 4V5L7 9H5a1 1 0 0 0-1 1ZM17 9a4 4 0 0 1 0 6",
  ton: "M4 7h14a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a1 1 0 0 1-1-1V6a2 2 0 0 1 2-2h10M16 13.5h.01",
  sun: "M12 3v2M12 19v2M5 5l1.4 1.4M17.6 17.6 19 19M3 12h2M19 12h2M5 19l1.4-1.4M17.6 6.4 19 5M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8",
  moon: "M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5Z",
};
const Ico = ({ d }) => (
  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={d} /></svg>
);

// الأقسام مجمّعة؛ كل صفحة تظهر فقط لمن يملك صلاحية قسمها
const GROUPS = [
  { title: "نظرة عامة", pages: [{ key: "ceo", label: "التقارير والإحصاءات", area: "ceo" }, { key: "system", label: "حالة النظام", area: "system" }] },
  { title: "المستخدمون", pages: [{ key: "users", label: "المستخدمون", area: "users" }] },
  { title: "المالية", pages: [
    { key: "packages", label: "الباقات", area: "packages" },
    { key: "rewards", label: "المكافآت والكوبونات", area: "rewards" },
    { key: "ton", label: "محفظة TON", area: "ton" },
  ] },
  { title: "الدعم", pages: [{ key: "support", label: "الدعم الفني الذكي", area: "support" }] },
  { title: "الإشعارات", pages: [
    { key: "notifications", label: "إرسال الإشعارات", area: "notifications" },
    { key: "announcements", label: "نافذة التحديثات", area: "notifications" },
  ] },
  { title: "النمو", pages: [{ key: "leaderboard", label: "ترتيب الأسبوع", area: "settings" }] },
  { title: "الإعدادات", pages: [{ key: "control", label: "مركز التحكم", area: "settings" }, { key: "servers", label: "خوادم MT5", area: "settings" }] },
  { title: "الإدارة", pages: [{ key: "staff", label: "فريق العمل", area: "staff" }, { key: "audit", label: "سجل العمليات", area: "audit" }] },
];
const ICON_OF = { ceo: I.ceo, system: I.system, users: I.users, packages: I.packages, rewards: I.rewards, leaderboard: I.leaderboard, control: I.control,
  servers: I.servers, staff: I.staff, audit: I.audit, support: I.support, notifications: I.notifications, announcements: I.announcements, ton: I.ton };

function useMobile() {
  const q = "(max-width: 900px)";
  const [m, setM] = useState(() => window.matchMedia(q).matches);
  useEffect(() => {
    const mq = window.matchMedia(q);
    const on = () => setM(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return m;
}

const THEME_KEY = "aw_admin_theme";
function useTheme() {
  const [theme, setTheme] = useState(() => {
    try { return localStorage.getItem(THEME_KEY) || "dark"; } catch { return "dark"; }
  });
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem(THEME_KEY, theme); } catch { /* تخزين غير متاح */ }
  }, [theme]);
  return [theme, () => setTheme((t) => (t === "dark" ? "light" : "dark"))];
}

export default function Dashboard({ me, onLogout }) {
  const perms = me?.perms || {};
  const groups = GROUPS.map((g) => ({ ...g, pages: g.pages.filter((p) => perms[p.area]) })).filter((g) => g.pages.length);
  const first = groups[0]?.pages[0]?.key || "ceo";
  const [page, setPage] = useState(() => {
    const h = window.location.hash.slice(1);
    return groups.some((g) => g.pages.some((p) => p.key === h)) ? h : first;
  });
  const [drawer, setDrawer] = useState(false);
  const [theme, toggleTheme] = useTheme();
  const mobile = useMobile();
  const go = (key) => groups.some((g) => g.pages.some((p) => p.key === key)) && setPage(key);
  useEffect(() => {
    window.history.replaceState(null, "", `#${page}`);
    setDrawer(false);
    window.scrollTo(0, 0);
  }, [page]);
  useEffect(() => {
    const onHash = () => {
      const h = window.location.hash.slice(1);
      if (groups.some((g) => g.pages.some((p) => p.key === h))) setPage(h);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  });
  const current = groups.flatMap((g) => g.pages).find((p) => p.key === page);
  const canWrite = (area) => perms[area] === "rw";

  const nav = (
    <>
      {groups.map((g) => (
        <div className="nav-group" key={g.title}>
          <span className="nav-group-title">{g.title}</span>
          {g.pages.map((p) => (
            <button key={p.key} className={`nav-item ${page === p.key ? "active" : ""}`} onClick={() => setPage(p.key)}>
              <Ico d={ICON_OF[p.key]} />
              <span>{p.label}</span>
            </button>
          ))}
        </div>
      ))}
      <div className="nav-footer">
        <div className="whoami">
          <b>{me?.name || "مرحبًا"}</b>
          <span className="muted">{me?.role_label} · <span className="mono">{me?.admin_id}</span></span>
        </div>
        <button className="theme-btn" onClick={toggleTheme}><Ico d={theme === "dark" ? I.sun : I.moon} /><span>{theme === "dark" ? "الوضع النهاري" : "الوضع الليلي"}</span></button>
        <button onClick={onLogout}>تسجيل الخروج</button>
      </div>
    </>
  );

  return (
    <div className="shell">
      <header className="mobile-bar">
        <img src={logo} alt="AW Robot" />
        <span className="mobile-title">{current?.label}</span>
        {mobile && <Alerts onGo={go} />}
        <button className="menu-btn" onClick={() => setDrawer(true)} aria-label="القائمة">
          <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16" /></svg>
        </button>
      </header>

      <nav className="nav">
        <div className="nav-brand"><img src={logo} alt="AW Robot" />{!mobile && <Alerts onGo={go} />}</div>
        {nav}
      </nav>

      {drawer && (
        <div className="drawer-backdrop" onClick={() => setDrawer(false)}>
          <nav className="drawer" onClick={(e) => e.stopPropagation()}>
            <div className="nav-brand"><img src={logo} alt="AW Robot" /><button className="close-btn" onClick={() => setDrawer(false)} aria-label="إغلاق">✕</button></div>
            {nav}
          </nav>
        </div>
      )}

      <main className="main fade-in" key={page}>
        {page === "ceo" && <Ceo />}
        {page === "users" && <Users canWrite={canWrite("users")} />}
        {page === "packages" && <Packages />}
        {page === "rewards" && <Rewards />}
        {page === "leaderboard" && <><div className="topbar"><h1>ترتيب الأسبوع</h1></div><LeaderboardSettings /></>}
        {page === "control" && <AppSettings />}
        {page === "servers" && <Servers />}
        {page === "staff" && <Staff />}
        {page === "audit" && <Audit />}
        {page === "system" && <SystemStatus />}
        {page === "support" && <Support canWrite={canWrite("support")} />}
        {page === "notifications" && <Notifications canWrite={canWrite("notifications")} />}
        {page === "announcements" && <Announcements canWrite={canWrite("notifications")} />}
        {page === "ton" && <TonWallet canWrite={canWrite("ton")} />}
      </main>
    </div>
  );
}
