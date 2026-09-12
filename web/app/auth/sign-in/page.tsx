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

export default function SignInPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState<"email" | "google" | null>(null);
  const [error, setError] = useState<SafeAuthError | null>(null);
  useSignedInRedirect();

  const submitEmail = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setPending("email");
    setError(null);
    try {
      const result = await authClient.signIn.email({ email, password });
      if (result.error) {
        setError(safeAuthError(result.error, "sign-in"));
        return;
      }
      router.replace("/");
      router.refresh();
    } catch (requestError) {
      setError(safeAuthError(requestError, "sign-in"));
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
      <h1>Sign in to CogniFlow</h1>
      <form className="auth-form" onSubmit={submitEmail}>
        <div className="auth-field">
          <label htmlFor="sign-in-email">Email</label>
          <input
            id="sign-in-email"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            autoComplete="email"
            required
          />
        </div>
        <PasswordField
          id="sign-in-password"
          label="Password"
          value={password}
          onChange={setPassword}
          autoComplete="current-password"
        />
        <Link className="auth-inline-link" href="/auth/forgot-password">
          Forgot password?
        </Link>
        <AuthErrorLine error={error} />
        <button type="submit" className="btn auth-submit" disabled={pending !== null}>
          {pending === "email" ? "Signing in…" : "Sign in"}
        </button>
      </form>
      <AuthDivider />
      <GoogleButton
        busy={pending === "google"}
        disabled={pending !== null}
        onClick={submitGoogle}
      />
      <p className="auth-foot">
        New to CogniFlow? <Link href="/auth/sign-up">Create an account</Link>
      </p>
    </AuthPage>
  );
}
