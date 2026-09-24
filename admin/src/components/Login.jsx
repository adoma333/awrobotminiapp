import React, { useState } from "react";
import { api, ApiError } from "../api";
import logo from "../assets/logo-wordmark.png";

export default function Login({ initialToken, onSuccess }) {
  const [token, setToken] = useState(initialToken || "");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(e) {
    e.preventDefault();
    if (!token.trim() || code.trim().length < 4) {
      setError("أدخل الرابط/الرمز كاملَين.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.verify(token.trim(), code.trim());
      onSuccess();
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError(
          err.detail === "wrong_code"
            ? "رمز التحقق غير صحيح."
            : "الرابط منتهي الصلاحية أو استُخدم من قبل. أرسل /admin للبوت من جديد."
        );
      } else {
        setError("تعذّر الاتصال بالخادم. حاول مجددًا.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={styles.wrap}>
      <form onSubmit={submit} style={styles.card} className="fade-in">
        <img src={logo} alt="AW ROBOT" style={styles.mark} />
        <h1 style={styles.title}>لوحة التحكم</h1>
        <p style={styles.hint}>
          أرسل <span className="mono" style={{ color: "var(--accent)" }}>/admin</span> لبوت
          تلجرام للحصول على رابط ورمز تحقق صالحَين 5 دقائق.
        </p>

        <label style={styles.label}>رمز التحقق</label>
        <input
          value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
          placeholder="000000"
          className="mono"
          style={{ fontSize: 20, letterSpacing: 4, textAlign: "center" }}
          inputMode="numeric"
          autoFocus={!!initialToken}
        />

        {!initialToken && (
          <>
            <label style={styles.label}>التوكن (من رابط البوت)</label>
            <input
              value={token}
              onChange={(e) => setToken(e.target.value.trim())}
              placeholder="token"
              className="mono"
            />
          </>
        )}

        {error && <div style={styles.error}>{error}</div>}

        <button type="submit" className="primary" disabled={busy} style={{ width: "100%", marginTop: 6, padding: "10px 14px" }}>
          {busy ? "جارٍ التحقق…" : "دخول"}
        </button>
      </form>
    </div>
  );
}

const styles = {
  wrap: {
    minHeight: "100%",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: 20,
  },
  card: {
    width: "100%",
    maxWidth: 360,
    background: "var(--surface)",
    border: "1px solid var(--border)",
    borderRadius: 16,
    padding: 28,
    boxShadow: "0 20px 60px rgba(0,0,0,.5)",
    display: "flex",
    flexDirection: "column",
    gap: 4,
  },
  mark: { height: 30, alignSelf: "center", marginBottom: 18 },
  title: { fontSize: 19, fontWeight: 600, margin: "0 0 6px" },
  hint: { color: "var(--muted)", fontSize: 13.5, margin: "0 0 18px", lineHeight: 1.6 },
  label: { fontSize: 12.5, color: "var(--muted)", margin: "10px 0 6px" },
  error: {
    marginTop: 10,
    fontSize: 13,
    color: "var(--bad)",
    background: "var(--bad-dim)",
    border: "1px solid var(--bad)",
    borderRadius: 6,
    padding: "8px 10px",
  },
};
