import React, { useEffect, useState } from "react";
import { api } from "./api";
import Login from "./components/Login";
import Dashboard from "./components/Dashboard";

export default function App() {
  const [phase, setPhase] = useState("loading"); // loading | login | dashboard
  const [adminId, setAdminId] = useState(null);
  const [initialToken] = useState(() => new URLSearchParams(window.location.search).get("token") || "");

  useEffect(() => {
    api
      .me()
      .then((r) => {
        setAdminId(r.admin_id);
        setPhase("dashboard");
      })
      .catch(() => setPhase("login"));
  }, []);

  function handleLoginSuccess() {
    window.history.replaceState({}, "", window.location.pathname);
    api.me().then((r) => {
      setAdminId(r.admin_id);
      setPhase("dashboard");
    });
  }

  function handleLogout() {
    api.logout().finally(() => {
      setAdminId(null);
      setPhase("login");
    });
  }

  if (phase === "loading") return null;
  if (phase === "login") return <Login initialToken={initialToken} onSuccess={handleLoginSuccess} />;
  return <Dashboard adminId={adminId} onLogout={handleLogout} />;
}
