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
  paused: boolean;
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
  paused: false,
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
    let wakeElapsedMs = 0;
    let visibleSince: number | null = document.hidden ? null : wakeStartedAt;
    let paused = document.hidden;
    let graceRemainingMs = CHECKING_GRACE_MS;
    let graceStartedAt: number | null = null;
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

    const visibleWakeElapsed = (now = Date.now()) =>
      wakeElapsedMs + (visibleSince == null ? 0 : now - visibleSince);

    const refreshWakeStartedAt = (now = Date.now()) => {
      wakeStartedAt = now - visibleWakeElapsed(now);
    };

    const pauseGrace = (now: number) => {
      if (graceStartedAt != null) {
        graceRemainingMs = Math.max(0, graceRemainingMs - (now - graceStartedAt));
        graceStartedAt = null;
      }
      clearGraceTimer();
    };

    const scheduleGrace = () => {
      clearGraceTimer();
      if (!mounted || document.hidden || state !== "checking") return;
      if (graceRemainingMs <= 0) {
        state = "waking";
        update({ state });
        return;
      }
      graceStartedAt = Date.now();
      graceTimer = window.setTimeout(() => {
        graceTimer = null;
        graceStartedAt = null;
        graceRemainingMs = 0;
        if (!mounted || document.hidden || state !== "checking") return;
        state = "waking";
        update({ state });
      }, graceRemainingMs);
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
      if (!mounted || document.hidden || state === "online" || state === "offline") return;
      const deadlineCycle = cycle;
      const remaining = Math.max(0, WAKE_WINDOW_MS - visibleWakeElapsed());
      wakeDeadlineTimer = window.setTimeout(() => {
        wakeDeadlineTimer = null;
        if (
          !mounted ||
          document.hidden ||
          deadlineCycle !== cycle ||
          state === "online"
        ) return;
        state = "offline";
        clearGraceTimer();
        clearScheduledProbe();
        update({ state });
        if (!probeInFlight) scheduleProbe(OFFLINE_INTERVAL_MS);
      }, remaining);
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
      if (state === "offline" || visibleWakeElapsed(completedAt) >= WAKE_WINDOW_MS) {
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
      const now = Date.now();
      wakeStartedAt = now;
      wakeElapsedMs = 0;
      visibleSince = document.hidden ? null : now;
      paused = document.hidden;
      attempts = 0;
      state = "waking";
      graceRemainingMs = 0;
      graceStartedAt = null;
      clearScheduledProbe();
      clearGraceTimer();
      scheduleWakeDeadline();
      update({ state, attempts, probeInFlight, wakeStartedAt, paused });
      if (probeInFlight) {
        pendingImmediateProbe = true;
        controller?.abort();
      } else if (document.hidden) {
        pendingImmediateProbe = true;
      } else {
        void probe();
      }
    };

    retryRef.current = restartWakeWindow;
    reportUnreachableRef.current = () => {
      if (state === "online") restartWakeWindow();
    };

    const onVisibilityChange = () => {
      if (document.hidden) {
        const now = Date.now();
        if (visibleSince != null) {
          wakeElapsedMs += now - visibleSince;
          visibleSince = null;
        }
        refreshWakeStartedAt(now);
        paused = true;
        clearScheduledProbe();
        clearWakeDeadline();
        pauseGrace(now);
        update({ paused, wakeStartedAt });
        return;
      }

      const now = Date.now();
      paused = false;
      visibleSince = now;
      refreshWakeStartedAt(now);
      update({ paused, wakeStartedAt });

      if (state !== "online") {
        clearScheduledProbe();
        scheduleWakeDeadline();
        scheduleGrace();
        if (!probeInFlight) {
          pendingImmediateProbe = false;
          void probe();
        } else {
          pendingImmediateProbe = true;
        }
      }
    };

    document.addEventListener("visibilitychange", onVisibilityChange);
    setSnapshot({ ...INITIAL_SNAPSHOT, wakeStartedAt, paused });
    if (!paused) {
      scheduleWakeDeadline();
      scheduleGrace();
      void probe();
    }

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
