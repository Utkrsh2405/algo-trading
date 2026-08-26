"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { login, signup, ApiError } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      if (mode === "login") {
        const res = await login(email, password);
        localStorage.setItem("access_token", res.access_token);
      } else {
        await signup(email, password, fullName || undefined);
        const res = await login(email, password);
        localStorage.setItem("access_token", res.access_token);
      }
      router.push("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-logo">
          <div className="login-logo-icon">⚡</div>
          AlgoTrader
        </div>

        <h1 className="login-title">
          {mode === "login" ? "Welcome back" : "Create account"}
        </h1>
        <p className="login-subtitle">
          {mode === "login"
            ? "Sign in to access your trading dashboard"
            : "Get started with your trading account"}
        </p>

        <form onSubmit={handleSubmit}>
          {mode === "signup" && (
            <div className="form-group">
              <label className="form-label" htmlFor="full-name">Full Name</label>
              <input
                id="full-name"
                type="text"
                className="form-input"
                placeholder="Shambhavi Verma"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                autoComplete="name"
              />
            </div>
          )}

          <div className="form-group">
            <label className="form-label" htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              className="form-input"
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="email"
            />
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              className="form-input"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete={mode === "login" ? "current-password" : "new-password"}
            />
          </div>

          {error && <p className="form-error">{error}</p>}

          <button
            id="submit-button"
            type="submit"
            className="btn-primary"
            disabled={loading}
          >
            {loading
              ? mode === "login" ? "Signing in…" : "Creating account…"
              : mode === "login" ? "Sign in" : "Create account"}
          </button>
        </form>

        <p className="form-link" onClick={() => { setMode(mode === "login" ? "signup" : "login"); setError(null); }}>
          {mode === "login"
            ? "Don't have an account? Sign up"
            : "Already have an account? Sign in"}
        </p>
      </div>
    </div>
  );
}
