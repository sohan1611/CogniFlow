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

import { useCallback, useState } from "react";

/** Kept in step with the .glass-sweep animation in globals.css. */
const SWEEP_MS = 620;

export type Tab = "plan" | "learn" | "progress";

const TABS: { id: Tab; label: string; icon: string }[] = [
  { id: "plan", label: "Learning Plan", icon: "◎" },
  { id: "learn", label: "Learn", icon: "✎" },
  { id: "progress", label: "Progress", icon: "◷" },
];

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
  children,
  sweeping,
}: {
  tab: Tab;
  onTab: (t: Tab) => void;
  name: string | null;
  children: React.ReactNode;
  sweeping: boolean;
}) {
  const initials = (name ?? "")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase())
    .join("") || "··";

  return (
    <>
      {sweeping && <div className="glass-sweep" aria-hidden />}
      <div className="shell">
        <header className="topbar">
          <div className="wordmark">
            Cogni<span>Flow</span>
          </div>

          <nav className="nav" aria-label="Sections">
            {TABS.map((t) => (
              <button
                key={t.id}
                aria-current={tab === t.id}
                onClick={() => onTab(t.id)}
                disabled={!name}
                title={!name ? "Tell me your name first" : undefined}
              >
                <span aria-hidden>{t.icon}</span>
                {t.label}
              </button>
            ))}
          </nav>

          <div className="who">
            <div className="avatar" aria-hidden>{initials}</div>
            <div>
              <b>{name ?? "Not signed in"}</b>
              {/* No email: there are no accounts, and inventing one on screen would be
                  the first dishonest pixel in the product. */}
              <small>{name ? "learner" : "enter a name to begin"}</small>
            </div>
          </div>
        </header>

        <div className="plate" style={{ viewTransitionName: "plate" }}>
          {children}
        </div>
      </div>
    </>
  );
}
