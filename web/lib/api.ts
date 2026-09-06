/**
 * The only place this app knows the engine exists.
 *
 * Every tutoring decision is made by the Python graph. Nothing in this frontend chooses
 * a skill, judges an answer, or moves a mastery score -- it renders what the engine
 * returns, exactly as the Streamlit UI does. If that ever stops being true, the two
 * surfaces will disagree about the same student, which is the failure this boundary
 * exists to prevent.
 */

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
      cache: "no-store",
    });
  } catch {
    // A dead engine and a wrong URL look identical from here, and both are worth
    // saying out loud rather than rendering an empty page.
    throw new ApiError(0, `Cannot reach the CogniFlow engine at ${BASE}.`);
  }
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new ApiError(response.status, detail.detail ?? response.statusText);
  }
  return response.json() as Promise<T>;
}

// ---------------------------------------------------------------- shapes
export type Health = {
  status: string;
  providers: string[];
  generation: "live" | "deterministic-templates";
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
  teaching_mode: string | null;
  difficulty: string | null;
  mastery: Record<string, number>;
  returning_to: string | null;
  recommended_next: string | null;
  session_status: string | null;
  events: TutorEvent[];
};

export type PlanSkill = {
  skill: string;
  /** Decided by the ENGINE. The UI must never recompute this: whether a skill is
   *  locked is a prerequisite judgement, and this system exists to make those. */
  state: "completed" | "locked" | "available";
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
  counts: { total: number; done: number; upcoming: number };
  skills: PlanSkill[];
};

export type Progress = {
  student_id: string;
  overall_mastery: number;
  skills: {
    skill: string;
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

// ---------------------------------------------------------------- calls
export const api = {
  health: () => request<Health>("/health"),

  startSession: (name: string) =>
    request<SessionStart>("/session", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),

  diagnosticQuestion: (id: string) =>
    request<DiagnosticStep>(`/session/${id}/diagnostic`),

  answerDiagnostic: (id: string, skill: string, code: string) =>
    request<{ skill: string; correct: boolean }>(`/session/${id}/diagnostic`, {
      method: "POST",
      body: JSON.stringify({ skill, code }),
    }),

  beginTutoring: (id: string, name: string, targetSkill?: string | null) =>
    request<TutorView>(`/session/${id}/start`, {
      method: "POST",
      body: JSON.stringify({ name, target_skill: targetSkill ?? null }),
    }),

  submit: (id: string, code: string) =>
    request<TutorView>(`/session/${id}/submit`, {
      method: "POST",
      body: JSON.stringify({ code }),
    }),

  /** Asking for help submits nothing and moves no mastery. The draft is sent
   *  because an unfinished attempt says more about where someone is stuck than
   *  the skill name does. */
  hints: (id: string, code: string) =>
    request<{ skill: string; hints: string[] }>(`/session/${id}/hints`, {
      method: "POST",
      body: JSON.stringify({ code }),
    }),

  plan: (id: string) => request<Plan>(`/student/${id}/plan`),

  progress: (id: string) => request<Progress>(`/student/${id}/progress`),
};
