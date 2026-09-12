"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { authClient } from "@/lib/auth/client";
import {
  AuthPage,
  PasswordField,
  isInvalidResetError,
  safeAuthError,
} from "../auth-ui";

export function ResetPasswordForm({ token }: { token: string }) {
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [pending, setPending] = useState(false);
  const [expired, setExpired] = useState(!token);
  const [updated, setUpdated] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (password.length < 8) {
      setError("Use at least 8 characters.");
      return;
    }
    if (password !== confirmation) {
      setError("Passwords do not match.");
      return;
    }

    setPending(true);
    setError(null);
    try {
      const result = await authClient.resetPassword({ newPassword: password, token });
      if (result.error) {
        if (isInvalidResetError(result.error)) {
          setExpired(true);
          return;
        }
        setError(safeAuthError(result.error, "other").message);
        return;
      }
      setUpdated(true);
    } catch (requestError) {
      setError(safeAuthError(requestError, "other").message);
    } finally {
      setPending(false);
    }
  };

  return (
    <AuthPage>
      <h1>Choose a new password</h1>
      {expired ? (
        <div className="auth-result">
          <p role="alert">This reset link has expired or was already used.</p>
          <Link className="auth-return-link" href="/auth/forgot-password">
            Request a new one
          </Link>
        </div>
      ) : updated ? (
        <div className="auth-result">
          <p className="auth-status" role="status">Password updated.</p>
          <Link className="auth-return-link" href="/auth/sign-in">Sign in</Link>
        </div>
      ) : (
        <form className="auth-form" onSubmit={submit}>
          <PasswordField
            id="new-password"
            label="New password"
            value={password}
            onChange={setPassword}
            autoComplete="new-password"
            describedBy="new-password-rule"
          />
          <p id="new-password-rule" className="auth-field-help">
            Use at least 8 characters.
          </p>
          <PasswordField
            id="confirm-password"
            label="Confirm password"
            value={confirmation}
            onChange={setConfirmation}
            autoComplete="new-password"
          />
          {error && <p className="auth-error" role="alert">{error}</p>}
          <button type="submit" className="btn auth-submit" disabled={pending}>
            {pending ? "Saving…" : "Save new password"}
          </button>
        </form>
      )}
    </AuthPage>
  );
}
