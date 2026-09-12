"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { authClient } from "@/lib/auth/client";

export const AUTH_SERVICE_ERROR =
  "We couldn't reach the sign-in service. Please try again.";

type AuthErrorKind = "credentials" | "exists" | "weak" | "service" | "other";

export type SafeAuthError = {
  kind: AuthErrorKind;
  message: string;
};

type ErrorRecord = {
  code?: unknown;
  status?: unknown;
  error?: unknown;
};

function authErrorDetails(error: unknown) {
  if (!error || typeof error !== "object") {
    return { code: "", status: 0 };
  }

  const record = error as ErrorRecord;
  const nested =
    record.error && typeof record.error === "object"
      ? (record.error as ErrorRecord)
      : null;
  const codeValue = record.code ?? nested?.code;
  const statusValue = record.status ?? nested?.status;

  return {
    code: typeof codeValue === "string" ? codeValue.toUpperCase() : "",
    status: typeof statusValue === "number" ? statusValue : 0,
  };
}

export function safeAuthError(
  error: unknown,
  action: "sign-in" | "sign-up" | "other",
): SafeAuthError {
  const { code, status } = authErrorDetails(error);

  if (status === 0 || status >= 500) {
    return { kind: "service", message: AUTH_SERVICE_ERROR };
  }
  if (
    action === "sign-in" &&
    (code === "INVALID_EMAIL_OR_PASSWORD" ||
      code === "INVALID_PASSWORD" ||
      status === 401)
  ) {
    return { kind: "credentials", message: "That email and password don't match." };
  }
  if (
    action === "sign-up" &&
    (code === "USER_ALREADY_EXISTS" ||
      code === "USER_ALREADY_EXISTS_USE_ANOTHER_EMAIL" ||
      status === 409)
  ) {
    return {
      kind: "exists",
      message: "An account with that email already exists.",
    };
  }
  if (code === "PASSWORD_TOO_SHORT") {
    return { kind: "weak", message: "Use at least 8 characters." };
  }
  return { kind: "other", message: "Something went wrong. Please try again." };
}

export function isNetworkAuthError(error: unknown) {
  const { status } = authErrorDetails(error);
  return status === 0 || status >= 500;
}

export function isInvalidResetError(error: unknown) {
  const { code, status } = authErrorDetails(error);
  return (
    code === "INVALID_TOKEN" ||
    code === "TOKEN_EXPIRED" ||
    status === 400 ||
    status === 401 ||
    status === 404 ||
    status === 410
  );
}

export function useSignedInRedirect() {
  const router = useRouter();
  const { data: session } = authClient.useSession();

  useEffect(() => {
    if (session?.user) {
      router.replace("/");
      router.refresh();
    }
  }, [router, session?.user]);
}

export function AuthPage({ children }: { children: ReactNode }) {
  return (
    <div className="auth-page">
      <div className="auth-shell">
        <div className="auth-wordmark" aria-label="CogniFlow">
          <span className="wordmark">
            Cogni<span className="wordmark-flow">Flow</span>
          </span>
        </div>
        <section className="card auth-card">{children}</section>
      </div>
    </div>
  );
}

export function PasswordField({
  id,
  label,
  value,
  onChange,
  autoComplete,
  describedBy,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  autoComplete: "current-password" | "new-password";
  describedBy?: string;
}) {
  const [visible, setVisible] = useState(false);

  return (
    <div className="auth-field">
      <label htmlFor={id}>{label}</label>
      <div className="password-field">
        <input
          id={id}
          type={visible ? "text" : "password"}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          autoComplete={autoComplete}
          aria-describedby={describedBy}
          minLength={autoComplete === "new-password" ? 8 : undefined}
          required
        />
        <button
          type="button"
          className="password-toggle"
          aria-label={visible ? `Hide ${label.toLowerCase()}` : `Show ${label.toLowerCase()}`}
          aria-pressed={visible}
          onClick={() => setVisible((current) => !current)}
        >
          {visible ? "Hide" : "Show"}
        </button>
      </div>
    </div>
  );
}

export function GoogleButton({
  busy,
  disabled,
  onClick,
}: {
  busy: boolean;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className="btn ghost auth-google"
      onClick={onClick}
      disabled={disabled}
    >
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path
          fill="#4285F4"
          d="M21.6 12.23c0-.71-.06-1.4-.18-2.06H12v3.89h5.38a4.6 4.6 0 0 1-1.99 3.02v2.52h3.23c1.89-1.74 2.98-4.3 2.98-7.37Z"
        />
        <path
          fill="#34A853"
          d="M12 22c2.7 0 4.96-.89 6.62-2.4l-3.23-2.52c-.9.6-2.04.96-3.39.96-2.6 0-4.81-1.76-5.6-4.13H3.06v2.6A10 10 0 0 0 12 22Z"
        />
        <path
          fill="#FBBC05"
          d="M6.4 13.91A6.02 6.02 0 0 1 6.08 12c0-.66.11-1.3.32-1.91v-2.6H3.06A10 10 0 0 0 2 12c0 1.61.39 3.14 1.06 4.51l3.34-2.6Z"
        />
        <path
          fill="#EA4335"
          d="M12 5.96c1.47 0 2.79.51 3.82 1.49l2.87-2.87A9.63 9.63 0 0 0 12 2a10 10 0 0 0-8.94 5.49l3.34 2.6C7.19 7.72 9.4 5.96 12 5.96Z"
        />
      </svg>
      {busy ? "Connecting…" : "Continue with Google"}
    </button>
  );
}

export function AuthDivider() {
  return <div className="auth-divider"><span>or</span></div>;
}

export function AuthErrorLine({ error }: { error: SafeAuthError | null }) {
  if (!error) return null;
  return (
    <p className="auth-error" role="alert">
      {error.message}
      {error.kind === "exists" && (
        <>
          {" "}
          <Link href="/auth/sign-in">Sign in instead?</Link>
        </>
      )}
    </p>
  );
}
