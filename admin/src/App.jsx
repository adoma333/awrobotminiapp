import React, { useEffect, useState } from "react";
import { api } from "./api";
import Login from "./components/Login";
import Dashboard from "./components/Dashboard";

export default function App() {
  const [phase, setPhase] = useState("loading"); // loading | login | dashboard
  const [me, setMe] = useState(null);
  const [initialToken] = useState(() => new URLSearchParams(window.location.search).get("token") || "");

  useEffect(() => {
    api
      .me()
      .then((r) => {
        setMe(r);
        setPhase("dashboard");
      })
      .catch(() => setPhase("login"));
  }, []);

  function handleLoginSuccess() {
    window.history.replaceState({}, "", window.location.pathname);
    api.me().then((r) => {
      setMe(r);
      setPhase("dashboard");
    });
  }

  function handleLogout() {
    api.logout().finally(() => {
      setMe(null);
      setPhase("login");
    });
  }

  if (phase === "loading") return null;
  if (phase === "login") return <Login initialToken={initialToken} onSuccess={handleLoginSuccess} />;
  return <Dashboard me={me} onLogout={handleLogout} />;
}
