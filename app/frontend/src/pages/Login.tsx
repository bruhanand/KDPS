import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { apiErrorMessage } from "../lib/api";
import { useAuth } from "../auth/AuthContext";
import { ThemeToggle } from "../theme/ThemeToggle";
import "./Login.css";

const DEMO: { label: string; username: string; password: string }[] = [
  { label: "Owner", username: "owner", password: "Owner@123" },
  { label: "HO Ops", username: "ops1", password: "Ops@123" },
  { label: "Accounts", username: "accounts1", password: "Acct@123" },
  { label: "Warehouse", username: "wh.patna", password: "Wh@123" },
  { label: "Store manager", username: "deo.manager", password: "Store@123" },
  { label: "Store cashier", username: "deo.cashier", password: "Store@123" },
];

export function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function doLogin(u: string, p: string) {
    setError("");
    setBusy(true);
    try {
      await login(u, p);
      navigate("/");
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    void doLogin(username.trim(), password);
  }

  return (
    <div className="login">
      <aside className="login-brand">
        <div className="login-brand-inner">
          <span className="brand-mark login-mark">K</span>
          <h1 className="login-title">KDPS Operating System</h1>
        </div>
      </aside>

      <main className="login-panel">
        <div className="login-theme">
          <ThemeToggle compact />
        </div>
        <form className="login-card" onSubmit={submit} data-testid="login-form">
          <p className="eyebrow">Sign in</p>
          <h2 className="h2" style={{ marginBottom: 18 }}>Welcome back</h2>

          <div className="field" style={{ marginBottom: 14 }}>
            <label htmlFor="username">Username</label>
            <input
              id="username"
              className="input"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoFocus
              data-testid="login-username"
            />
          </div>
          <div className="field" style={{ marginBottom: 18 }}>
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              className="input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              data-testid="login-password"
            />
          </div>

          {error && (
            <div className="login-error" data-testid="login-error">
              {error}
            </div>
          )}

          <button className="btn btn-cta btn-block btn-lg" disabled={busy} data-testid="login-submit">
            {busy ? "Signing in…" : "Sign in"}
          </button>

          <div className="login-demo">
            <span>Demo logins</span>
            <div className="login-demo-chips">
              {DEMO.map((d) => (
                <button
                  key={d.username}
                  type="button"
                  className="chip chip-navy"
                  disabled={busy}
                  onClick={() => {
                    setUsername(d.username);
                    setPassword(d.password);
                    void doLogin(d.username, d.password);
                  }}
                  data-testid={`demo-${d.username}`}
                >
                  {d.label}
                </button>
              ))}
            </div>
          </div>
        </form>
      </main>
    </div>
  );
}
