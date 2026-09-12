/**
 * The only place this app knows the engine exists.
 *
 * Every tutoring decision is made by the Python graph. Nothing in this frontend chooses
 * a skill, judges an answer, or moves a mastery score -- it renders what the engine
 * returns, exactly as the Streamlit UI does. If that ever stops being true, the two
 * surfaces will disagree about the same student, which is the failure this boundary
 * exists to prevent.
 */

import { authClient } from "@/lib/auth/client";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
const JWT_REFRESH_WINDOW_SECONDS = 60;
const READ_TIMEOUT_MS = 20_000;
const TUTOR_TIMEOUT_MS = 120_000;
const HEALTH_TIMEOUT_MS = 25_000;
const TIMEOUT_MESSAGE = "This is taking longer than usual. Please try again.";

declare const jwtBrand: unique symbol;
type Jwt = string & { readonly [jwtBrand]: true };

type CachedJwt = {
  token: Jwt;
  expiresAt: number;
};

let cachedJwt: CachedJwt | null = null;
let jwtRequest: Promise<Jwt> | null = null;

type AuthRouteFailure = {
  route: "/api/auth/token" | "/api/auth/get-session";
  status: number;
  unauthenticated: boolean;
  unavailable: boolean;
};

type AuthTokenAttempt =
  | { token: Jwt; failure: null }
  | { token: null; failure: AuthRouteFailure };

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly kind: "network" | "http" | "timeout",
    readonly recovery?: "sign-out",
  ) {
    super(message);
  }
}

function decodeJwtSegment(segment: string): unknown {
  const base64 = segment.replace(/-/g, "+").replace(/_/g, "/");
  const padded = base64.padEnd(Math.ceil(base64.length / 4) * 4, "=");
  return JSON.parse(atob(padded)) as unknown;
}

function usableJwt(value: unknown): Jwt | null {
  if (typeof value !== "string") return null;
  const segments = value.split(".");
  if (
    segments.length !== 3 ||
    segments.some((segment) => !/^[A-Za-z0-9_-]+$/.test(segment))
  ) {
    return null;
  }

  try {
    const header = decodeJwtSegment(segments[0]);
    if (
      !header ||
      typeof header !== "object" ||
      !("alg" in header) ||
      typeof (header as { alg?: unknown }).alg !== "string" ||
      !(header as { alg: string }).alg.trim()
    ) {
      return null;
    }
    return value as Jwt;
  } catch {
    return null;
  }
}

function jwtExpiration(token: Jwt) {
  try {
    const payload = token.split(".")[1];
    if (!payload) return 0;
    const decoded = decodeJwtSegment(payload);
    if (!decoded || typeof decoded !== "object" || !("exp" in decoded)) return 0;
    const exp = (decoded as { exp?: unknown }).exp;
    return typeof exp === "number" ? exp : 0;
  } catch {
    return 0;
  }
}

export function clearCachedJwt() {
  cachedJwt = null;
  jwtRequest = null;
}

function sendToSignIn() {
  clearCachedJwt();
  if (typeof window !== "undefined") {
    window.location.assign("/auth/sign-in");
  }
}

function cacheJwt(token: Jwt) {
  cachedJwt = {
    token,
    expiresAt: jwtExpiration(token),
  };
  return token;
}

function errorStatus(error: unknown) {
  if (!error || typeof error !== "object" || !("status" in error)) return 0;
  const status = (error as { status?: unknown }).status;
  return typeof status === "number" ? status : 0;
}

function authRouteFailure(
  route: AuthRouteFailure["route"],
  status: number,
  unauthenticated = status === 401,
  unavailable = status === 0 || status >= 500,
): AuthRouteFailure {
  return {
    route,
    status,
    unauthenticated,
    unavailable,
  };
}

function warnAuthFailures(failures: AuthRouteFailure[]) {
  console.warn("Neon Auth did not provide a usable JWT", {
    failures: failures.map(({ route, status }) => ({ step: route, status })),
  });
}

async function tokenRouteJwt(): Promise<AuthTokenAttempt> {
  try {
    const response = await fetch("/api/auth/token", {
      credentials: "include",
      cache: "no-store",
      headers: { accept: "application/json" },
    });
    if (!response.ok) {
      return {
        token: null,
        failure: authRouteFailure(
          "/api/auth/token",
          response.status,
          response.status === 401,
          response.status !== 401,
        ),
      };
    }

    const body: unknown = await response.json().catch(() => null);
    const candidate =
      typeof body === "string"
        ? body
        : body && typeof body === "object" && "token" in body
          ? (body as { token?: unknown }).token
          : null;
    const token = usableJwt(candidate);
    if (token) return { token, failure: null };
    return {
      token: null,
      failure: authRouteFailure("/api/auth/token", response.status),
    };
  } catch (error) {
    return {
      token: null,
      failure: authRouteFailure("/api/auth/token", errorStatus(error)),
    };
  }
}

async function sessionRouteJwt(): Promise<AuthTokenAttempt> {
  let headerJwt: string | null = null;
  let responseStatus: number | null = null;
  try {
    const result = await authClient.getSession({
      fetchOptions: {
        credentials: "include",
        onSuccess: (ctx) => {
          responseStatus = ctx.response.status;
          headerJwt = ctx.response.headers.get("set-auth-jwt");
        },
      },
    });
    const headerToken = usableJwt(headerJwt);
    if (headerToken) return { token: headerToken, failure: null };

    const sessionToken = usableJwt(result.data?.session?.token);
    if (sessionToken) return { token: sessionToken, failure: null };

    const status = result.error?.status ?? responseStatus ?? 200;
    const hasSession = Boolean(result.data?.session && result.data.user);
    return {
      token: null,
      failure: authRouteFailure(
        "/api/auth/get-session",
        status,
        status === 401 || (status === 200 && !hasSession),
      ),
    };
  } catch (error) {
    return {
      token: null,
      failure: authRouteFailure("/api/auth/get-session", errorStatus(error)),
    };
  }
}

async function loadJwt() {
  const tokenAttempt = await tokenRouteJwt();
  if (tokenAttempt.token !== null) return cacheJwt(tokenAttempt.token);

  if (tokenAttempt.failure.unauthenticated) {
    warnAuthFailures([tokenAttempt.failure]);
    sendToSignIn();
    throw new ApiError(
      401,
      "Your session has ended. Please sign in again.",
      "http",
    );
  }

  const sessionAttempt = await sessionRouteJwt();
  if (sessionAttempt.token !== null) return cacheJwt(sessionAttempt.token);

  const tokenFailure = tokenAttempt.failure;
  const sessionFailure = sessionAttempt.failure;
  warnAuthFailures([tokenFailure, sessionFailure]);
  if (tokenFailure.unauthenticated && sessionFailure.unauthenticated) {
    sendToSignIn();
    throw new ApiError(
      401,
      "Your session has ended. Please sign in again.",
      "http",
    );
  }

  const unavailableFailure = [tokenFailure, sessionFailure].find(
    (failure) => failure.unavailable,
  );
  if (unavailableFailure) {
    throw new ApiError(
      unavailableFailure.status,
      "We couldn't reach the sign-in service. Please try again.",
      "http",
    );
  }

  throw new ApiError(
    sessionFailure.status,
    "You're signed in, but we couldn't start a tutoring session. Try signing out and back in.",
    "http",
    "sign-out",
  );
}

async function getJwt(forceRefresh = false) {
  const now = Date.now() / 1000;
  if (
    !forceRefresh &&
    cachedJwt &&
    cachedJwt.expiresAt - now > JWT_REFRESH_WINDOW_SECONDS
  ) {
    return cachedJwt.token;
  }

  if (!forceRefresh && jwtRequest) return jwtRequest;
  const request = loadJwt();
  jwtRequest = request;
  try {
    return await request;
  } finally {
    if (jwtRequest === request) jwtRequest = null;
  }
}

function isPublicEnginePath(path: string) {
  return path === "/health" || path === "/skills";
}

async function engineFetch(
  path: string,
  init: RequestInit | undefined,
  baseHeaders: Headers,
  jwt: Jwt | null,
) {
  const headers = new Headers(baseHeaders);
  if (jwt) headers.set("Authorization", `Bearer ${jwt}`);

  try {
    return await fetch(`${BASE}${path}`, {
      ...init,
      headers,
      cache: "no-store",
    });
  } catch (error) {
    // request() owns deadline errors. Let an abort retain its identity so a slow
    // request is not mistaken for an unreachable engine.
    if (init?.signal?.aborted) throw error;
    console.warn("Tutoring engine request could not connect", {
      method: init?.method ?? "GET",
      path,
      base: BASE,
    });
    throw new ApiError(0, "We couldn't reach the tutoring engine.", "network");
  }
}

async function request<T>(
  path: string,
  init?: RequestInit,
  timeoutMs = READ_TIMEOUT_MS,
): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body == null) {
    headers.delete("Content-Type");
  } else if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const controller = new AbortController();
  const externalSignal = init?.signal;
  const forwardAbort = () => controller.abort(externalSignal?.reason);
  if (externalSignal?.aborted) {
    forwardAbort();
  } else {
    externalSignal?.addEventListener("abort", forwardAbort, { once: true });
  }

  let timedOut = false;
  let timeoutHandle: ReturnType<typeof setTimeout> | null = null;
  const deadline = new Promise<never>((_, reject) => {
    timeoutHandle = setTimeout(() => {
      timedOut = true;
      controller.abort();
      reject(new ApiError(0, TIMEOUT_MESSAGE, "timeout"));
    }, timeoutMs);
  });

  const execute = async () => {
    const requestInit = { ...init, signal: controller.signal };
    const needsAuth = !isPublicEnginePath(path);
    let jwt = needsAuth ? await getJwt() : null;
    let response = await engineFetch(path, requestInit, headers, jwt);

    if (needsAuth && response.status === 401) {
      jwt = await getJwt(true);
      response = await engineFetch(path, requestInit, headers, jwt);
      if (response.status === 401) {
        sendToSignIn();
        throw new ApiError(
          401,
          "Your session has ended. Please sign in again.",
          "http",
        );
      }
    }

    if (!response.ok) {
      const payload: unknown = await response.json().catch(() => null);
      const detail =
        payload && typeof payload === "object" && "detail" in payload
          ? (payload as { detail?: unknown }).detail
          : null;
      const usableDetail = typeof detail === "string" && detail.trim() ? detail : null;
      const message =
        response.status === 403
          ? "That progress belongs to a different account."
          : response.status === 404
            ? "We couldn't find that record. Try starting again."
            : response.status >= 500
              ? "The tutoring engine hit a problem. Please try again in a moment."
              : usableDetail ?? "Something went wrong. Please try again.";
      throw new ApiError(response.status, message, "http");
    }
    return response.json() as Promise<T>;
  };

  try {
    return await Promise.race([execute(), deadline]);
  } catch (error) {
    if (timedOut) throw new ApiError(0, TIMEOUT_MESSAGE, "timeout");
    throw error;
  } finally {
    if (timeoutHandle != null) clearTimeout(timeoutHandle);
    externalSignal?.removeEventListener("abort", forwardAbort);
  }
}

// ---------------------------------------------------------------- shapes
export type LanguageOption = {
  value: string;
  label: string;
};

export type Health = {
  status: string;
  providers: string[];
  generation: "live" | "deterministic-templates";
  languages?: LanguageOption[];
};

export type SessionStart = {
  student_id: string;
  returning: boolean;
  needs_diagnostic: boolean;
};

export type DiagnosticStep =
  | {
      complete: false;
      skill: string;
      prompt: string;
      starter_code: string;
      answered: number;
      skipped: Record<string, string>;
    }
  | {
      complete: true;
      weakest_skill: string | null;
      missing_prerequisites: string[];
      confidence: number;
      mastery: Record<string, number>;
      evidence: string[];
    };

export type TutorEvent = {
  node: string;
  type: string;
  payload: Record<string, unknown>;
  reason: string | null;
  evidence: string[];
};

export type TutorView = {
  student_id: string;
  name: string;
  awaiting_student: boolean;
  suspended_at: string | null;
  problem: {
    title: string | null;
    prompt: string | null;
    starter_code: string;
    expected_output: string;
    assessment_type: string | null;
    grounded_in: string[];
  } | null;
  feedback: {
    passed: boolean | null;
    score: number | null;
    message: string | null;
    /** True when the failure was OURS. The student must never be shown our outage
     *  as though it were their mistake. */
    was_our_fault: boolean;
  } | null;
  target_skill: string | null;
  /** Confidence per skill: how much evidence stands behind each mastery estimate. */
  confidence: Record<string, number>;
  /** Skills we have actually observed. Anything absent is a prior, not a measurement. */
  measured: string[];
  language?: string | null;
  teaching_mode: string | null;
  difficulty: string | null;
  mastery: Record<string, number>;
  returning_to: string | null;
  recommended_next: string | null;
  session_status: string | null;
  /** Set only on the problem where the level actually moved, and null otherwise.
   *  Carries the guard's own reason rather than a rephrasing of it: if the sentence on
   *  screen can drift from the one in the log, it stops being evidence. */
  difficulty_change: {
    from: string;
    to: string;
    direction: "up" | "down";
    reason: string | null;
    /** Built from the ladder for the student. `reason` stays the guard's exact
     *  words for the audit trail; this is the one a learner can act on. */
    student_reason: string | null;
    demands: string | null;
    concepts: string[];
  } | null;
  events: TutorEvent[];
};

export type PlanSkill = {
  skill: string;
  /** Decided by the ENGINE. The UI must never recompute this: whether a skill is
   *  locked is a prerequisite judgement, and this system exists to make those.
   *
   *  "provisional" is mastery without the evidence to trust it -- one right answer puts
   *  BKT at 0.85 mastery on 0.22 confidence, which the guard will not ADVANCE on. Shown
   *  as its own thing because calling it "completed" told students they had finished
   *  five topics they had answered one question about. */
  state: "completed" | "provisional" | "locked" | "available";
  mastery: number;
  confidence: number;
  attempts: number;
  prerequisites: string[];
  blocked_by: string[];
  unlocks: string[];
  misconceptions: string[];
  overcome: string[];
};

export type Plan = {
  student_id: string;
  suggested_next: string | null;
  counts: { total: number; done: number; provisional: number; upcoming: number };
  skills: PlanSkill[];
  total_attempts: number;
};

export type Progress = {
  student_id: string;
  overall_mastery: number;
  skills: {
    skill: string;
    /** Decided by the ENGINE, from the same predicate as the learning plan. No
     *  threshold comparison belongs in this file: a client that decides for itself
     *  whether 0.85-at-0.22 counts as mastered is how the plan came to award five
     *  "Completed" topics the guard would never have advanced on. "locked" is absent
     *  because it is a routing judgement, and this screen is about belief. */
    state: "completed" | "provisional" | "unproven";
    mastery: number;
    confidence: number;
    attempts: number;
    misconceptions: string[];
    overcome: string[];
  }[];
  recent_attempts: {
    skill: string;
    outcome: string;
    mastery_before: number;
    mastery_after: number;
    at: string;
  }[];
  total_attempts: number;
};

export type Activity = {
  student_id: string;
  days: number;
  since: string;
  total: number;
  attempts: {
    at: string;
    skill: string;
    outcome: string;
    correct: boolean;
  }[];
};

// ---------------------------------------------------------------- calls
export const api = {
  health: (signal?: AbortSignal) =>
    request<Health>("/health", { signal }, HEALTH_TIMEOUT_MS),

  startSession: (name: string, language?: string) =>
    request<SessionStart>("/session", {
      method: "POST",
      body: JSON.stringify(language ? { name, language } : { name }),
    }),

  diagnosticQuestion: (id: string) =>
    request<DiagnosticStep>(`/session/${id}/diagnostic`),

  answerDiagnostic: (id: string, skill: string, code: string) =>
    request<{ skill: string; correct: boolean }>(`/session/${id}/diagnostic`, {
      method: "POST",
      body: JSON.stringify({ skill, code }),
    }, TUTOR_TIMEOUT_MS),

  beginTutoring: (id: string, name: string, targetSkill?: string | null) =>
    request<TutorView>(`/session/${id}/start`, {
      method: "POST",
      body: JSON.stringify({ name, target_skill: targetSkill ?? null }),
    }, TUTOR_TIMEOUT_MS),

  submit: (id: string, code: string) =>
    request<TutorView>(`/session/${id}/submit`, {
      method: "POST",
      body: JSON.stringify({ code }),
    }, TUTOR_TIMEOUT_MS),

  /** Asking for help submits nothing and moves no mastery. The draft is sent
   *  because an unfinished attempt says more about where someone is stuck than
   *  the skill name does. */
  hints: (id: string, code: string) =>
    request<{ skill: string; hints: string[] }>(`/session/${id}/hints`, {
      method: "POST",
      body: JSON.stringify({ code }),
    }, TUTOR_TIMEOUT_MS),

  plan: (id: string) => request<Plan>(`/student/${id}/plan`),

  progress: (id: string) => request<Progress>(`/student/${id}/progress`),

  activity: (id: string, days = 120) =>
    request<Activity>(`/student/${id}/activity?days=${days}`),
};
