"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { authClient } from "@/lib/auth/client";
import {
  AuthDivider,
  AuthErrorLine,
  AuthPage,
  GoogleButton,
  PasswordField,
  safeAuthError,
  useSignedInRedirect,
  type SafeAuthError,
} from "../auth-ui";

export default function SignUpPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState<"email" | "google" | null>(null);
  const [error, setError] = useState<SafeAuthError | null>(null);
  useSignedInRedirect();

  const submitEmail = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (password.length < 8) {
      setError({ kind: "weak", message: "Use at least 8 characters." });
      return;
    }

    setPending("email");
    setError(null);
    try {
      const result = await authClient.signUp.email({ name, email, password });
      if (result.error) {
        setError(safeAuthError(result.error, "sign-up"));
        return;
      }
      router.replace("/");
      router.refresh();
    } catch (requestError) {
      setError(safeAuthError(requestError, "sign-up"));
    } finally {
      setPending(null);
    }
  };

  const submitGoogle = async () => {
    setPending("google");
    setError(null);
    try {
      const result = await authClient.signIn.social({
        provider: "google",
        callbackURL: "/",
      });
      if (result.error) {
        setError(safeAuthError(result.error, "other"));
        setPending(null);
      }
    } catch (requestError) {
      setError(safeAuthError(requestError, "other"));
      setPending(null);
    }
  };

  return (
    <AuthPage>
      <h1>Create your account</h1>
      <form className="auth-form" onSubmit={submitEmail}>
        <div className="auth-field">
          <label htmlFor="sign-up-name">Name</label>
          <input
            id="sign-up-name"
            type="text"
            value={name}
            onChange={(event) => setName(event.target.value)}
            autoComplete="name"
            required
          />
        </div>
        <div className="auth-field">
          <label htmlFor="sign-up-email">Email</label>
          <input
            id="sign-up-email"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            autoComplete="email"
            required
          />
        </div>
        <PasswordField
          id="sign-up-password"
          label="Password"
          value={password}
          onChange={setPassword}
          autoComplete="new-password"
          describedBy="sign-up-password-rule"
        />
        <p id="sign-up-password-rule" className="auth-field-help">
          Use at least 8 characters.
        </p>
        <AuthErrorLine error={error} />
        <button type="submit" className="btn auth-submit" disabled={pending !== null}>
          {pending === "email" ? "Creating account…" : "Create account"}
        </button>
      </form>
      <AuthDivider />
      <GoogleButton
        busy={pending === "google"}
        disabled={pending !== null}
        onClick={submitGoogle}
      />
      <p className="auth-foot">
        Already have an account? <Link href="/auth/sign-in">Sign in</Link>
      </p>
    </AuthPage>
  );
}
