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
import type { Health } from "@/lib/api";

/** Kept in step with the .glass-sweep animation in globals.css. */
const SWEEP_MS = 620;

export type Tab = "plan" | "learn" | "progress";
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
  onChangeName,
  name,
  health,
  children,
  sweeping,
}: {
  tab: Tab;
  onTab: (t: Tab) => void;
  onChangeName: () => void;
  name: string | null;
  health: Health | null;
  children: React.ReactNode;
  sweeping: boolean;
}) {
  const [moreOpen, setMoreOpen] = useState(false);
  const [theme, setTheme] = useState<ThemeChoice>("system");
  const dialogRef = useRef<HTMLDivElement>(null);
  const headerTriggerRef = useRef<HTMLButtonElement>(null);
  const bottomTriggerRef = useRef<HTMLButtonElement>(null);
  const dotTriggerRef = useRef<HTMLButtonElement>(null);
  const lastTriggerRef = useRef<HTMLButtonElement | null>(null);

  const initials = name
    ? name
        .split(/\s+/)
        .filter(Boolean)
        .slice(0, 2)
        .map((w) => w[0]?.toUpperCase())
        .join("") || name[0]?.toUpperCase() || ""
    : "";
  const hasTemplateNotice = health?.generation === "deterministic-templates";

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

  const changeName = () => {
    closeMore();
    onChangeName();
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
              <div className="wordmark">
                Cogni<span>Flow</span>
                {hasTemplateNotice && (
                  <button
                    ref={dotTriggerRef}
                    type="button"
                    className="engine-dot"
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
                aria-current={tab === t.id ? "page" : undefined}
                onClick={() => onTab(t.id)}
                disabled={!name}
                title={!name ? "Tell me your name first" : undefined}
              >
                <span aria-hidden>{t.icon}</span>
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
              {name ? initials : "👤"}
            </span>
            <span className="who-text">
              <b>{name ?? "No learner yet"}</b>
              {/* No email: there are no accounts, and inventing one on screen would be
                  the first dishonest pixel in the product. */}
              <small>{name ? "learner" : "enter a name to begin"}</small>
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
            aria-current={tab === t.id ? "page" : undefined}
            onClick={() => onTab(t.id)}
            disabled={!name}
            title={!name ? "Tell me your name first" : undefined}
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
          initials={initials}
          health={health}
          theme={theme}
          onClose={closeMore}
          onChangeName={changeName}
          onTheme={applyTheme}
        />
      )}
    </>
  );
}

function MoreSheet({
  dialogRef,
  name,
  initials,
  health,
  theme,
  onClose,
  onChangeName,
  onTheme,
}: {
  dialogRef: React.RefObject<HTMLDivElement | null>;
  name: string | null;
  initials: string;
  health: Health | null;
  theme: ThemeChoice;
  onClose: () => void;
  onChangeName: () => void;
  onTheme: (theme: ThemeChoice) => void;
}) {
  const providersPresent = (health?.providers.length ?? 0) > 0;
  const generationText = !health
    ? "Checking engine status"
    : providersPresent
      ? "Live model generation"
      : "Built-in templates. Every tutoring decision is still computed exactly as it would be live; only the exercise wording is templated.";
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
              {name ? initials : "👤"}
            </span>
            <div>
              <h3>{name ?? "No learner yet"}</h3>
              <p className="muted">learner</p>
            </div>
          </div>
        </section>

        <section className="more-section">
          <button type="button" className="sheet-action" onClick={onChangeName}>
            Change name
          </button>
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
          <h3>Engine status</h3>
          <p className="muted">{generationText}</p>
          {corpus && corpus !== "ready" && <p className="muted">Corpus: {corpus}</p>}
        </section>
      </div>
    </div>
  );
}
