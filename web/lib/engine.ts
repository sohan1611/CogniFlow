"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api, type Health } from "@/lib/api";

export type EngineState = "checking" | "waking" | "online" | "offline";

export type EngineStatus = {
  state: EngineState;
  health: Health | null;
  attempts: number;
  lastCheckedAt: number | null;
  retry: () => void;
  reportUnreachable: () => void;
  probeInFlight: boolean;
  wakeStartedAt: number | null;
};

type EngineSnapshot = Omit<EngineStatus, "retry" | "reportUnreachable">;

// The first probe gets a brief grace period so a healthy engine does not flash a
// waking message during an ordinary connection.
const CHECKING_GRACE_MS = 2_500;
// Three minutes is about three times the measured cold start, leaving room for the
// free tier's variable scheduling and interpreter startup time.
const WAKE_WINDOW_MS = 180_000;
// Five seconds between wake attempts gives the engine time to advance without
// flooding it while it boots.
const PROBE_INTERVAL_MS = 5_000;
// A hung connection is aborted after 25 seconds so it counts as one failed attempt
// instead of stopping the wake loop forever.
const PROBE_TIMEOUT_MS = 25_000;
// An offline engine is checked every 30 seconds so recovery is automatic without
// keeping up the more frequent cold-start cadence indefinitely.
const OFFLINE_INTERVAL_MS = 30_000;

const TEMPLATE_GENERATION_DETAIL =
  "Built-in templates. Every tutoring decision is still computed exactly as it would be live; only the exercise wording is templated.";

export function engineCopy(status: Pick<EngineStatus, "state" | "health">) {
  switch (status.state) {
    case "checking":
      return {
        title: "Checking the tutoring engine",
        detail: "One moment.",
        startLabel: "Checking…",
      };
    case "waking":
      return {
        title: "Waking the tutoring engine",
        detail:
          "It sleeps after 15 quiet minutes and usually takes about a minute to come back. This page starts by itself once it answers.",
        startLabel: "Waking the engine…",
      };
    case "online":
      return {
        title: "Tutoring engine online",
        detail: status.health?.providers.length
          ? "Live model generation"
          : TEMPLATE_GENERATION_DETAIL,
        startLabel: "Start Learning",
      };
    case "offline":
      return {
        title: "Can't reach the tutoring engine right now",
        detail:
          "It may still be starting, or it may be briefly down. We'll keep trying every 30 seconds — you don't need to reload.",
        startLabel: "Engine offline",
      };
  }
}

const INITIAL_SNAPSHOT: EngineSnapshot = {
  state: "checking",
  health: null,
  attempts: 0,
  lastCheckedAt: null,
  probeInFlight: false,
  wakeStartedAt: null,
};

export function useEngineStatus(): EngineStatus {
  const [snapshot, setSnapshot] = useState<EngineSnapshot>(INITIAL_SNAPSHOT);
  const retryRef = useRef<() => void>(() => undefined);
  const reportUnreachableRef = useRef<() => void>(() => undefined);

  useEffect(() => {
    let mounted = true;
    let state: EngineState = "checking";
    let health: Health | null = null;
    let attempts = 0;
    let wakeStartedAt = Date.now();
    let cycle = 0;
    let probeInFlight = false;
    let pendingImmediateProbe = false;
    let scheduledProbe: number | null = null;
    let graceTimer: number | null = null;
    let wakeDeadlineTimer: number | null = null;
    let probeTimer: number | null = null;
    let controller: AbortController | null = null;

    const update = (next: Partial<EngineSnapshot>) => {
      if (!mounted) return;
      setSnapshot((current) => ({ ...current, ...next }));
    };

    const clearScheduledProbe = () => {
      if (scheduledProbe == null) return;
      window.clearTimeout(scheduledProbe);
      scheduledProbe = null;
    };

    const clearGraceTimer = () => {
      if (graceTimer == null) return;
      window.clearTimeout(graceTimer);
      graceTimer = null;
    };

    const clearWakeDeadline = () => {
      if (wakeDeadlineTimer == null) return;
      window.clearTimeout(wakeDeadlineTimer);
      wakeDeadlineTimer = null;
    };

    const scheduleProbe = (delay: number) => {
      clearScheduledProbe();
      if (!mounted || document.hidden || state === "online") return;
      scheduledProbe = window.setTimeout(() => {
        scheduledProbe = null;
        void probe();
      }, delay);
    };

    const scheduleWakeDeadline = () => {
      clearWakeDeadline();
      const deadlineCycle = cycle;
      wakeDeadlineTimer = window.setTimeout(() => {
        wakeDeadlineTimer = null;
        if (!mounted || deadlineCycle !== cycle || state === "online") return;
        state = "offline";
        clearGraceTimer();
        clearScheduledProbe();
        update({ state });
        if (!probeInFlight) scheduleProbe(OFFLINE_INTERVAL_MS);
      }, WAKE_WINDOW_MS);
    };

    const probe = async () => {
      if (!mounted || document.hidden || state === "online") return;
      if (probeInFlight) {
        pendingImmediateProbe = true;
        return;
      }

      probeInFlight = true;
      attempts += 1;
      const probeCycle = cycle;
      const probeController = new AbortController();
      controller = probeController;
      update({ attempts, probeInFlight: true, wakeStartedAt });
      probeTimer = window.setTimeout(() => probeController.abort(), PROBE_TIMEOUT_MS);

      let answer: Health | null = null;
      try {
        answer = await api.health(probeController.signal);
      } catch {
        // A failed probe is represented by the status state below. ApiError already
        // keeps the developer detail out of the student-facing copy.
      }

      const completedAt = Date.now();
      if (probeTimer != null) {
        window.clearTimeout(probeTimer);
        probeTimer = null;
      }
      if (controller === probeController) controller = null;
      probeInFlight = false;

      if (!mounted) return;
      if (probeCycle !== cycle) {
        update({ probeInFlight: false });
        if (pendingImmediateProbe && !document.hidden) {
          pendingImmediateProbe = false;
          void probe();
        }
        return;
      }

      if (answer) {
        pendingImmediateProbe = false;
        clearScheduledProbe();
        clearGraceTimer();
        clearWakeDeadline();
        state = "online";
        health = answer;
        update({
          state,
          health,
          attempts,
          lastCheckedAt: completedAt,
          probeInFlight: false,
          wakeStartedAt,
        });
        return;
      }

      update({ lastCheckedAt: completedAt, probeInFlight: false });
      if (state === "offline" || completedAt - wakeStartedAt >= WAKE_WINDOW_MS) {
        state = "offline";
        clearGraceTimer();
        update({ state });
        scheduleProbe(OFFLINE_INTERVAL_MS);
      } else {
        scheduleProbe(PROBE_INTERVAL_MS);
      }
    };

    const restartWakeWindow = () => {
      cycle += 1;
      wakeStartedAt = Date.now();
      attempts = 0;
      state = "waking";
      clearScheduledProbe();
      clearGraceTimer();
      scheduleWakeDeadline();
      update({ state, attempts, probeInFlight, wakeStartedAt });
      if (probeInFlight) {
        pendingImmediateProbe = true;
        controller?.abort();
      } else if (!document.hidden) {
        void probe();
      }
    };

    retryRef.current = restartWakeWindow;
    reportUnreachableRef.current = () => {
      if (state === "online") restartWakeWindow();
    };

    const onVisibilityChange = () => {
      if (document.hidden) {
        clearScheduledProbe();
        return;
      }
      if (state !== "online") {
        clearScheduledProbe();
        if (!probeInFlight) void probe();
      }
    };

    document.addEventListener("visibilitychange", onVisibilityChange);
    setSnapshot({ ...INITIAL_SNAPSHOT, wakeStartedAt });
    scheduleWakeDeadline();
    graceTimer = window.setTimeout(() => {
      graceTimer = null;
      if (!mounted || state !== "checking") return;
      state = "waking";
      update({ state });
    }, CHECKING_GRACE_MS);
    void probe();

    return () => {
      mounted = false;
      cycle += 1;
      clearScheduledProbe();
      clearGraceTimer();
      clearWakeDeadline();
      if (probeTimer != null) window.clearTimeout(probeTimer);
      controller?.abort();
      document.removeEventListener("visibilitychange", onVisibilityChange);
      retryRef.current = () => undefined;
      reportUnreachableRef.current = () => undefined;
    };
  }, []);

  const retry = useCallback(() => retryRef.current(), []);
  const reportUnreachable = useCallback(() => reportUnreachableRef.current(), []);

  return { ...snapshot, retry, reportUnreachable };
}
