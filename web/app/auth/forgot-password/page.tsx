"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { authClient } from "@/lib/auth/client";
import {
  AUTH_SERVICE_ERROR,
  AuthPage,
  isNetworkAuthError,
} from "../auth-ui";

const RESET_SENTENCE =
  "If an account exists for that email, a reset link is on its way. It expires in 15 minutes.";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [pending, setPending] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      const result = await authClient.requestPasswordReset({
        email,
        redirectTo: `${window.location.origin}/auth/reset-password`,
      });
      if (result.error && isNetworkAuthError(result.error)) {
        setError(AUTH_SERVICE_ERROR);
        return;
      }
      setSent(true);
    } catch {
      setError(AUTH_SERVICE_ERROR);
    } finally {
      setPending(false);
    }
  };

  return (
    <AuthPage>
      <h1>Reset your password</h1>
      {sent ? (
        <p className="auth-status" role="status">{RESET_SENTENCE}</p>
      ) : (
        <form className="auth-form" onSubmit={submit}>
          <div className="auth-field">
            <label htmlFor="reset-email">Email</label>
            <input
              id="reset-email"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              autoComplete="email"
              required
            />
          </div>
          {error && <p className="auth-error" role="alert">{error}</p>}
          <button type="submit" className="btn auth-submit" disabled={pending}>
            {pending ? "Sending…" : "Send reset link"}
          </button>
        </form>
      )}
      <Link className="auth-return-link" href="/auth/sign-in">Back to sign in</Link>
    </AuthPage>
  );
}
