"use client";

/**
 * The chrome: dark shell, glass nav, and the transition that carries one view into the
 * next.
 *
 * The glass is a finish painted OVER a swap, never the mechanism of it. An earlier
 * version drove the swap through the View Transitions API, which morphs beautifully and
 * silently dropped state changes when React was mid-render. A decorative effect must
 * never be able to eat a state transition, so the sweep is now a plain overlay: same
 * feel, works in every browser, and cannot fail in a way that costs the user anything.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { clearCachedJwt, type Health } from "@/lib/api";
import { authClient } from "@/lib/auth/client";
import { engineCopy, type EngineStatus } from "@/lib/engine";

/** Kept in step with the .glass-sweep animation in globals.css. */
const SWEEP_MS = 620;
const VERSION_LABEL = "v1.0";

/** "detail" is deliberately NOT in TABS. It is the tutor's own working notes -- the
 *  decision trail and its diagnoses -- which are written ABOUT a student rather than to
 *  them, so it is reachable from the More sheet and never occupies a bottom-bar slot a
 *  learner has to walk past. */
export type Tab = "plan" | "learn" | "progress" | "detail";
type ThemeChoice = "light" | "dark" | "system";

const TABS: { id: Tab; label: string; mobileLabel: string; icon: string }[] = [
  { id: "plan", label: "Learning Plan", mobileLabel: "Plan", icon: "◎" },
  { id: "learn", label: "Learn", mobileLabel: "Learn", icon: "✎" },
  { id: "progress", label: "Progress", mobileLabel: "Progress", icon: "◷" },
];
const THEME_OPTIONS: ThemeChoice[] = ["light", "dark", "system"];
const THEME_LABEL: Record<ThemeChoice, string> = {
  light: "Light",
  dark: "Dark",
  system: "System",
};

type HealthWithCorpus = Health & { corpus?: unknown };

/** Swap a view behind a sheet of glass. */
export function useGlassSwap() {
  const [sweeping, setSweeping] = useState(false);

  const swap = useCallback((change: () => void) => {
    setSweeping(true);
    window.setTimeout(() => setSweeping(false), SWEEP_MS);

    // The state change is applied here, unconditionally, and NOT from inside a
    // transition callback.
    //
    // The tempting version wraps it in `startViewTransition(() => flushSync(change))`,
    // which gives a true cross-fade morph. It also loses the change: flushSync silently
    // no-ops while React is already rendering, and after a fifteen-second API call it
    // very often is. That cost a tab switch that never happened while the data behind
    // it had loaded fine -- a decorative effect quietly eating a state transition.
    //
    // So the glass is painted over the swap rather than driving it. The sweep is a
    // fixed overlay with its own backdrop-filter; it animates identically in every
    // browser, needs no API support, and cannot swallow anything.
    change();
  }, []);

  return { swap, sweeping };
}

export function Shell({
  tab,
  onTab,
  name,
  email,
  hasLearner,
  engine,
  children,
  sweeping,
}: {
  tab: Tab;
  onTab: (t: Tab) => void;
  name: string;
  email: string;
  hasLearner: boolean;
  engine: EngineStatus;
  children: React.ReactNode;
  sweeping: boolean;
}) {
  const [moreOpen, setMoreOpen] = useState(false);
  const [theme, setTheme] = useState<ThemeChoice>("system");
  const [signingOut, setSigningOut] = useState(false);
  const [signOutError, setSignOutError] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const headerTriggerRef = useRef<HTMLButtonElement>(null);
  const bottomTriggerRef = useRef<HTMLButtonElement>(null);
  const dotTriggerRef = useRef<HTMLButtonElement>(null);
  const lastTriggerRef = useRef<HTMLButtonElement | null>(null);

  const initials =
    name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((word) => word[0]?.toUpperCase())
      .join("") || name[0]?.toUpperCase() || "";
  const hasTemplateNotice = engine.health?.generation === "deterministic-templates";

  const openMore = (trigger: HTMLButtonElement | null) => {
    lastTriggerRef.current = trigger;
    setMoreOpen(true);
  };

  const applyTheme = useCallback((next: ThemeChoice) => {
    setTheme(next);
    if (next === "system") {
      document.documentElement.removeAttribute("data-theme");
    } else {
      document.documentElement.dataset.theme = next;
    }
    try {
      localStorage.setItem("cogniflow-theme", next);
    } catch {}
  }, []);

  const closeMore = useCallback(() => {
    setMoreOpen(false);
    window.setTimeout(() => lastTriggerRef.current?.focus({ preventScroll: true }), 0);
  }, []);

  useEffect(() => {
    try {
      const stored = localStorage.getItem("cogniflow-theme");
      if (stored === "light" || stored === "dark" || stored === "system") {
        setTheme(stored);
        if (stored === "system") {
          document.documentElement.removeAttribute("data-theme");
        } else {
          document.documentElement.dataset.theme = stored;
        }
      }
    } catch {
      const stamped = document.documentElement.dataset.theme;
      setTheme(stamped === "light" || stamped === "dark" ? stamped : "system");
    }
  }, []);

  useEffect(() => {
    if (!moreOpen) return;
    window.setTimeout(() => dialogRef.current?.focus({ preventScroll: true }), 0);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeMore();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [closeMore, moreOpen]);

  const signOut = async () => {
    setSigningOut(true);
    setSignOutError(null);
    try {
      const result = await authClient.signOut();
      if (result.error) {
        setSignOutError(
          result.error.status === 0 || result.error.status >= 500
            ? "We couldn't reach the sign-in service. Please try again."
            : "Something went wrong. Please try again.",
        );
        return;
      }
      clearCachedJwt();
      window.location.assign("/auth/sign-in");
    } catch {
      setSignOutError("We couldn't reach the sign-in service. Please try again.");
    } finally {
      setSigningOut(false);
    }
  };

  return (
    <>
      {sweeping && <div className="glass-sweep" aria-hidden />}
      <div className="shell">
        <header className="topbar">
          <div className="brand">
            <div className="brand-tile" aria-hidden>
              CF
            </div>
            <div className="brand-copy">
              <div className="brand-line">
                <div className="wordmark">
                  Cogni<span className="wordmark-flow">Flow</span>
                </div>
                <span className="version-chip">{VERSION_LABEL}</span>
                {hasTemplateNotice && (
                  <button
                    ref={dotTriggerRef}
                    type="button"
                    className="engine-dot engine-dot-inline"
                    aria-label="Built-in templates status"
                    aria-expanded={moreOpen}
                    aria-haspopup="dialog"
                    onClick={() => openMore(dotTriggerRef.current)}
                  >
                    <span aria-hidden />
                  </button>
                )}
              </div>
              <p className="tagline">AI-powered adaptive learning</p>
            </div>
          </div>

          <nav className="nav" aria-label="Sections">
            {TABS.map((t) => (
              <button
                key={t.id}
                aria-current={hasLearner && tab === t.id ? "page" : undefined}
                onClick={() => onTab(t.id)}
                disabled={!hasLearner}
                title={!hasLearner ? "Start learning first" : undefined}
              >
                {t.label}
              </button>
            ))}
          </nav>

          <button
            ref={headerTriggerRef}
            type="button"
            className="who"
            aria-label="Open learner and engine status"
            aria-expanded={moreOpen}
            aria-haspopup="dialog"
            onClick={() => openMore(headerTriggerRef.current)}
          >
            <span className="avatar" aria-hidden>
              {initials}
            </span>
            <span className="who-text">
              <b>{name}</b>
              <small>learner</small>
            </span>
          </button>
        </header>

        <div className="plate" style={{ viewTransitionName: "plate" }}>
          {children}
        </div>
      </div>

      <nav className="bottom-nav" aria-label="Sections">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            aria-current={hasLearner && tab === t.id ? "page" : undefined}
            onClick={() => onTab(t.id)}
            disabled={!hasLearner}
            title={!hasLearner ? "Start learning first" : undefined}
          >
            <span aria-hidden>{t.icon}</span>
            {t.mobileLabel}
          </button>
        ))}
        <button
          ref={bottomTriggerRef}
          type="button"
          className={moreOpen ? "open" : undefined}
          aria-expanded={moreOpen}
          aria-haspopup="dialog"
          onClick={() => openMore(bottomTriggerRef.current)}
        >
          <span aria-hidden>•••</span>
          More
        </button>
      </nav>

      {moreOpen && (
        <MoreSheet
          dialogRef={dialogRef}
          name={name}
          email={email}
          initials={initials}
          hasLearner={hasLearner}
          engine={engine}
          theme={theme}
          onClose={closeMore}
          onSignOut={signOut}
          signingOut={signingOut}
          signOutError={signOutError}
          onTheme={applyTheme}
          onOpenDetail={() => {
            if (!hasLearner) return;
            closeMore();
            onTab("detail");
          }}
        />
      )}
    </>
  );
}

function MoreSheet({
  dialogRef,
  name,
  email,
  initials,
  hasLearner,
  engine,
  theme,
  onClose,
  onSignOut,
  signingOut,
  signOutError,
  onTheme,
  onOpenDetail,
}: {
  dialogRef: React.RefObject<HTMLDivElement | null>;
  name: string;
  email: string;
  initials: string;
  hasLearner: boolean;
  engine: EngineStatus;
  theme: ThemeChoice;
  onClose: () => void;
  onSignOut: () => void;
  signingOut: boolean;
  signOutError: string | null;
  onTheme: (theme: ThemeChoice) => void;
  onOpenDetail: () => void;
}) {
  const health = engine.health;
  const copy = engineCopy(engine);
  const languageLabels = (health?.languages ?? []).map((option) => option.label);
  const runsText = languageLabels.length > 0 ? languageLabels.join(", ") : "Not reported";
  const corpus =
    health && typeof (health as HealthWithCorpus).corpus === "string"
      ? String((health as HealthWithCorpus).corpus)
      : null;

  return (
    <div className="more-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div
        ref={dialogRef}
        className="more-sheet"
        role="dialog"
        aria-modal="true"
        aria-labelledby="more-title"
        tabIndex={-1}
      >
        <div className="sheet-head">
          <h2 id="more-title">More</h2>
          <button type="button" className="sheet-close" aria-label="Close more sheet" onClick={onClose}>
            ×
          </button>
        </div>

        <section className="more-section">
          <div className="who-row">
            <span className="avatar" aria-hidden>
              {initials}
            </span>
            <div>
              <h3>{name}</h3>
              <p className="muted">{email}</p>
            </div>
          </div>
        </section>

        <section className="more-section">
          <button
            type="button"
            className="sheet-action"
            onClick={onSignOut}
            disabled={signingOut}
          >
            {signingOut ? "Signing out…" : "Sign out"}
          </button>
          {signOutError && <p className="err sheet-availability" role="alert">{signOutError}</p>}
        </section>

        <section className="more-section">
          <h3>Appearance</h3>
          <div className="theme-toggle" role="radiogroup" aria-label="Appearance">
            {THEME_OPTIONS.map((option) => (
              <button
                key={option}
                type="button"
                role="radio"
                aria-checked={theme === option}
                onClick={() => onTheme(option)}
              >
                {THEME_LABEL[option]}
              </button>
            ))}
          </div>
        </section>

        <section className="more-section">
          <h3>Session detail</h3>
          <p className="muted">
            Every decision the tutor made this session, and the notes it wrote while
            diagnosing your work.
          </p>
          <button
            type="button"
            className="sheet-action"
            onClick={onOpenDetail}
            disabled={!hasLearner}
            title={!hasLearner ? "Start learning first" : undefined}
          >
            Open session detail
          </button>
          {!hasLearner && <p className="muted sheet-availability">Available once you&apos;ve started.</p>}
        </section>

        <section className="more-section">
          <h3>Engine status</h3>
          <p className="muted engine-copy-title">{copy.title}</p>
          <p className="muted engine-copy-detail">{copy.detail}</p>
          {engine.state === "online" && <p className="muted">Runs: {runsText}</p>}
          {corpus && corpus !== "ready" && <p className="muted">Corpus: {corpus}</p>}
          {engine.state === "offline" && (
            <button
              type="button"
              className="btn engine-retry"
              onClick={engine.retry}
              disabled={engine.probeInFlight}
            >
              {engine.probeInFlight ? "Checking…" : "Try again now"}
            </button>
          )}
        </section>
      </div>
    </div>
  );
}
