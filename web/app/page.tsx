"use client";

/**
 * The student experience, as a small state machine behind glass.
 *
 *   name -> diagnostic -> plan <-> learn <-> progress
 *
 * Transitions are driven by what the engine returns. This component knows how to draw a
 * problem; it does not know how a problem is chosen, and it must not learn.
 */

import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  api,
  type Activity,
  type DiagnosticStep,
  type Health,
  type Plan,
  type Progress,
  type TutorEvent,
  type TutorView,
} from "@/lib/api";
import { StudentDashboard } from "./dashboard";
import { CodeEditor } from "./editor";
import { ActivityPanel, LearningPlan, pretty } from "./plan";
import { Shell, type Tab, useGlassSwap } from "./shell";

type Stage = "name" | "diagnostic" | "app";

export default function Page() {
  const [stage, setStage] = useState<Stage>("name");
  const [tab, setTab] = useState<Tab>("plan");
  const [name, setName] = useState("");
  const [id, setId] = useState("");
  const [health, setHealth] = useState<Health | null>(null);
  const [reachable, setReachable] = useState<boolean | null>(null);
  const [waking, setWaking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [step, setStep] = useState<DiagnosticStep | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [view, setView] = useState<TutorView | null>(null);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [activity, setActivity] = useState<Activity | null>(null);
  const [code, setCode] = useState("");
  const [hints, setHints] = useState<string[]>([]);
  const [shown, setShown] = useState(0);

  const { swap, sweeping } = useGlassSwap();

  useEffect(() => {
    // Checked once, up front. A student clicking Start and getting a raw fetch error is
    // told nothing they can act on; a deployment whose engine is unset or asleep should
    // say which, before they have typed anything.
    //
    // The retries are not defensive padding. The engine runs on a free tier that
    // suspends itself after fifteen idle minutes and answers the first request with a
    // 502 while it boots, so a single probe would report a perfectly healthy service as
    // dead to whoever happens to arrive first -- which, for a link sent to judges, is
    // exactly who arrives first.
    let cancelled = false;
    const slow = window.setTimeout(() => {
      if (!cancelled) setWaking(true);
    }, 2500);

    const probe = (attemptsLeft: number): void => {
      api
        .health()
        .then((h) => {
          if (cancelled) return;
          setHealth(h);
          setReachable(true);
        })
        .catch(() => {
          if (cancelled) return;
          if (attemptsLeft > 0) {
            window.setTimeout(() => probe(attemptsLeft - 1), 5000);
            return;
          }
          setReachable(false);
        });
    };
    probe(12);

    return () => {
      cancelled = true;
      window.clearTimeout(slow);
    };
  }, []);

  const guard = useCallback(async (work: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await work();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, []);

  // -------------------------------------------------------------- actions
  const begin = () =>
    guard(async () => {
      const session = await api.startSession(name);
      setId(session.student_id);
      if (session.needs_diagnostic) {
        const first = await api.diagnosticQuestion(session.student_id);
        setStep(first);
        setCode(first.complete ? "" : first.starter_code);
        swap(() => setStage("diagnostic"));
      } else {
        setPlan(await api.plan(session.student_id));
        swap(() => setStage("app"));
      }
    });

  const answer = (submitted: string) =>
    guard(async () => {
      if (!step || step.complete) return;
      await api.answerDiagnostic(id, step.skill, submitted);
      const next = await api.diagnosticQuestion(id);
      setStep(next);
      setCode(next.complete ? "" : next.starter_code);
    });

  const enterApp = () =>
    guard(async () => {
      setPlan(await api.plan(id));
      swap(() => {
        setStage("app");
        setTab("plan");
      });
    });

  const startSkill = (skill: string) =>
    guard(async () => {
      const next = await api.beginTutoring(id, name, skill);
      setView(next);
      setCode(next.problem?.starter_code ?? "");
      setHints([]);
      setShown(0);
      swap(() => setTab("learn"));
    });

  const submit = () =>
    guard(async () => {
      const next = await api.submit(id, code);
      setView(next);
      setCode(next.problem?.starter_code ?? "");
      setHints([]);
      setShown(0);
      setPlan(await api.plan(id)); // mastery moved, so the plan did too
    });

  const askForHint = () =>
    guard(async () => {
      const ladder = hints.length ? hints : (await api.hints(id, code)).hints;
      setHints(ladder);
      setShown((n) => Math.min(n + 1, ladder.length));
    });

  const changeTab = (next: Tab) =>
    guard(async () => {
      if (next === "plan") setPlan(await api.plan(id));
      // The detail view reads the diagnoses off the student profile, so it needs the
      // same fetch Progress does -- otherwise it shows whatever was cached from a
      // Progress visit that may never have happened.
      if (next === "detail") setProgress(await api.progress(id));
      if (next === "progress") {
        const [nextProgress, nextActivity] = await Promise.all([
          api.progress(id),
          api.activity(id),
        ]);
        setProgress(nextProgress);
        setActivity(nextActivity);
      }
      swap(() => setTab(next));
    });

  const changeName = () => {
    swap(() => {
      setStage("name");
      setTab("plan");
      setName("");
      setId("");
      setView(null);
      setPlan(null);
      setProgress(null);
      setActivity(null);
      setStep(null);
      setHints([]);
      setShown(0);
      setCode("");
      setError(null);
    });
  };

  // -------------------------------------------------------------- render
  return (
    <Shell
      tab={tab}
      onTab={changeTab}
      onChangeName={changeName}
      name={stage === "name" ? null : name}
      health={health}
      sweeping={sweeping}
    >
      {reachable === null && waking && (
        <div className="note">
          <strong>Waking the tutoring engine</strong>
          It sleeps when nobody is using it and takes up to a minute to come back. This
          page will start on its own once it answers.
        </div>
      )}

      {reachable === false && (
        <div className="note warn">
          <strong>The tutoring engine is not reachable</strong>
          This page is only the surface — the tutor itself runs as a separate service.
          Nothing below will work until it is running and{" "}
          <code>NEXT_PUBLIC_API_URL</code> points at it.
        </div>
      )}

      {health && health.generation !== "live" && (
        <div className="note warn templates-banner">
          <strong>Running on built-in templates</strong>
          No model provider is configured, so exercise wording is templated. Every
          tutoring decision below is still computed exactly as it would be live.
        </div>
      )}
      {error && <p className="err">{error}</p>}

      {stage === "name" && (
        <div className="hero">
          <div className="hero-pill">AI Tutor</div>
          <h1>
            Your personalized
            <br />
            learning journey starts here.
          </h1>
          <p className="sub">
            We&apos;ll find what you know, spot the gaps underneath, and pick your next
            challenge from there.
          </p>

          <div className="step-strip" aria-label="Tutor flow">
            <span>Assess</span>
            <span>Understand</span>
            <span>Adapt</span>
            <span>Improve</span>
          </div>

          <div className="name-block">
            <label htmlFor="nm">What should I call you?</label>
            <p className="muted">We&apos;ll use your name to remember what you know between visits.</p>
            <div className="name-field">
              <span aria-hidden>👤</span>
              <input
                id="nm"
                type="text"
                value={name}
                placeholder="Enter your name"
                inputMode="text"
                autoComplete="given-name"
                enterKeyHint="go"
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && name.trim() && begin()}
              />
            </div>
            <button
              className="btn hero-cta"
              onClick={begin}
              disabled={busy || !name.trim() || reachable !== true}
            >
              {busy
                ? "Starting…"
                : reachable === false
                  ? "Engine offline"
                  : reachable === null
                    ? "Waking the engine…"
                    : "Start Learning"}
            </button>
          </div>

          <div className="feature-grid">
            <article className="feature">
              <span aria-hidden>◎</span>
              <h3>Personalized</h3>
              <p className="muted">Adapts to your strengths and gaps</p>
            </article>
            <article className="feature">
              <span aria-hidden>✎</span>
              <h3>Practice</h3>
              <p className="muted">Real code, run against real tests</p>
            </article>
            <article className="feature">
              <span aria-hidden>◷</span>
              <h3>Progress</h3>
              <p className="muted">Track what you have actually shown</p>
            </article>
            <article className="feature">
              <span aria-hidden>✦</span>
              <h3>AI Tutor</h3>
              <p className="muted">Guidance the moment you are stuck</p>
            </article>
          </div>
        </div>
      )}

      {stage === "diagnostic" && step && !step.complete && (
        <div style={{ maxWidth: 720, margin: "0 auto" }}>
          <h1>Quick check</h1>
          <p className="sub">
            No grade here — getting one wrong just means we start there.
            {Object.keys(step.skipped).length > 0 &&
              ` ${Object.keys(step.skipped).length} question(s) already skipped: you showed me the answer by missing what they build on.`}
          </p>
          <div className="card" style={{ marginTop: 18 }}>
            <div className="top">
              <h3>{pretty(step.skill)}</h3>
              <span className="chip">Question {step.answered + 1}</span>
            </div>
            <p className="desc" style={{ whiteSpace: "pre-wrap" }}>{step.prompt}</p>
            <CodeEditor
              value={code}
              onChange={setCode}
              ariaLabel="Diagnostic answer"
            />
            <div className="row" style={{ marginTop: 12 }}>
              <button className="btn" onClick={() => answer(code)} disabled={busy}>
                {busy ? "Checking…" : "Submit"}
              </button>
              <button className="btn ghost" onClick={() => answer("")} disabled={busy}>
                I don&apos;t know this one
              </button>
            </div>
          </div>
        </div>
      )}

      {stage === "diagnostic" && step?.complete && (
        <div style={{ maxWidth: 720, margin: "0 auto" }}>
          <h1>Here is what I found</h1>
          <div className="card">
            <p>
              <strong>Start here:</strong>{" "}
              {step.weakest_skill ? pretty(step.weakest_skill) : "nothing — you are ahead of this course"}
            </p>
            {step.missing_prerequisites.length > 0 && (
              <p className="sub">
                Gaps underneath it: {step.missing_prerequisites.join(", ")}
              </p>
            )}
            <p className="muted">
              Confidence in this picture: {(step.confidence * 100).toFixed(0)}%
            </p>
            <button className="btn" onClick={enterApp} disabled={busy} style={{ marginTop: 10 }}>
              See my plan
            </button>
          </div>
        </div>
      )}

      {stage === "app" && tab === "plan" && plan && (
        <LearningPlan
          plan={plan}
          activeSkill={view?.awaiting_student ? view.target_skill : null}
          onStart={startSkill}
          busy={busy}
        />
      )}

      {stage === "app" && tab === "learn" && (
        <Learn
          view={view}
          code={code}
          setCode={setCode}
          onSubmit={submit}
          onHint={askForHint}
          hints={hints.slice(0, shown)}
          exhausted={shown > 0 && shown >= hints.length}
          busy={busy}
        />
      )}

      {stage === "app" && tab === "detail" && (
        <DetailView events={view?.events ?? []} progress={progress} />
      )}

      {stage === "app" && tab === "progress" && progress && activity && (
        <ProgressView progress={progress} activity={activity} />
      )}
    </Shell>
  );
}

function Learn({
  view,
  code,
  setCode,
  onSubmit,
  onHint,
  hints,
  exhausted,
  busy,
}: {
  view: TutorView | null;
  code: string;
  setCode: (v: string) => void;
  onSubmit: () => void;
  onHint: () => void;
  hints: string[];
  exhausted: boolean;
  busy: boolean;
}) {
  if (!view) {
    return (
      <div style={{ maxWidth: 620, margin: "6vh auto", textAlign: "center" }}>
        <h1>Nothing in progress</h1>
        <p className="sub">Pick a skill from your learning plan to begin.</p>
      </div>
    );
  }
  const fb = view.feedback;
  return (
    <div className="columns">
      <section>
        {/* Our failure is never shown as the student's mistake. */}
        {/* A student moved to a harder problem with no explanation has been handed a
            harder problem for no visible reason, which reads as the system being
            arbitrary. The reason shown here is the policy guard's own, carried through
            unchanged. */}
        {view.difficulty_change && (
          <div className={`note ${view.difficulty_change.direction === "up" ? "info" : "warn"}`}>
            <strong>
              {view.difficulty_change.direction === "up"
                ? `Difficulty increased: ${view.difficulty_change.from} → ${view.difficulty_change.to}`
                : `Difficulty adjusted: ${view.difficulty_change.from} → ${view.difficulty_change.to}`}
            </strong>
            {view.difficulty_change.student_reason ?? view.difficulty_change.reason}
            {view.difficulty_change.concepts.length > 0 && (
              <span className="muted" style={{ display: "block", marginTop: 6 }}>
                Now testing: {view.difficulty_change.concepts.map((c) => c.replace(/_/g, " ")).join(", ")}
              </span>
            )}
          </div>
        )}

        {fb?.was_our_fault && (
          <div className="note ours">
            <strong>Something on our side went wrong</strong>
            Your submission and your progress have been preserved, and nothing was
            counted against you.
          </div>
        )}
        {fb && !fb.was_our_fault && fb.passed && (
          <div className="note good">
            <strong>Correct</strong>
            {fb.score != null && `Passed every test case (${(fb.score * 100).toFixed(0)}%).`}
          </div>
        )}
        {fb && !fb.was_our_fault && fb.passed === false && fb.message && (
          <div className="note warn">
            <strong>Not quite — but the mistake is a useful one</strong>
            {fb.message}
          </div>
        )}

        {/* The redirect, explained. Without this it reads from the student's side as
            the tutor changing the subject for no reason. */}
        {view.returning_to && view.returning_to !== view.target_skill && (
          <div className="note info">
            <strong>Let&apos;s back up for a moment</strong>
            We&apos;re working on <b>{view.target_skill}</b> first, then going straight
            back to <b>{view.returning_to}</b> — that is still what you came here for.
          </div>
        )}

        {view.problem && view.awaiting_student ? (
          <div className="card">
            <div className="top">
              <h3>{view.problem.title}</h3>
              <span className="chip">{view.difficulty}</span>
            </div>
            <p className="exercise-prompt">{view.problem.prompt}</p>
            {view.problem.expected_output && (
              <p className="muted">
                Expected output: <code>{view.problem.expected_output}</code>
              </p>
            )}
            <CodeEditor
              value={code}
              onChange={setCode}
              ariaLabel="Exercise answer"
            />
            <div className="row" style={{ marginTop: 12 }}>
              <button className="btn" onClick={onSubmit} disabled={busy}>
                {busy ? "Running…" : "Submit"}
              </button>
              <button className="btn ghost" onClick={onHint} disabled={busy || exhausted}>
                {exhausted ? "No more hints" : "I'm stuck — give me a hint"}
              </button>
            </div>

            {hints.map((hint, i) => (
              <div className="note info" key={i} style={{ marginTop: 12 }}>
                <strong>Hint {i + 1}</strong>
                {hint}
              </div>
            ))}
            {exhausted && (
              <p className="muted" style={{ marginTop: 10 }}>
                That&apos;s as much as I can give you without doing it for you — have a
                go, and I&apos;ll tell you exactly what went wrong.
              </p>
            )}
            {view.problem.grounded_in.length > 0 && (
              <p className="muted" style={{ marginTop: 12, marginBottom: 0 }}>
                Based on: {view.problem.grounded_in.join(", ")}
              </p>
            )}
          </div>
        ) : (
          <div className="card">
            <h3>Session {view.session_status ?? "finished"}</h3>
            {view.recommended_next && (
              <p className="sub">
                Recommended next: <code>{view.recommended_next}</code>
              </p>
            )}
          </div>
        )}
      </section>

      <aside className="panel">
        <div className="head">
          <h2>What the tutor believes</h2>
        </div>
        {Object.entries(view.mastery)
          .sort((a, b) => a[1] - b[1])
          .map(([skill, value]) => (
            <div key={skill} style={{ marginBottom: 12 }}>
              <div className="spread">
                <span style={{ fontWeight: skill === view.target_skill ? 700 : 400 }}>
                  {pretty(skill)}
                </span>
                <span className="muted">{value.toFixed(2)}</span>
              </div>
              <div className="bar">
                <span style={{ width: `${Math.min(1, value) * 100}%` }} />
              </div>
            </div>
          ))}
      </aside>
    </div>
  );
}

/* Server-assigned standing, rendered. Deliberately a lookup rather than a threshold
   comparison: this file must never decide for itself what counts as mastered. */
const STANDING_CHIP: Record<string, string> = {
  completed: "chip done",
  provisional: "chip maybe",
  unproven: "chip",
};
const STANDING_LABEL: Record<string, string> = {
  completed: "Confirmed",
  provisional: "Looks good",
  unproven: "Not shown yet",
};

/* The tutor's own working notes, kept off every student-facing screen.
 *
 * This was previously a permanent right-hand panel on the learning plan, which meant a
 * learner opening the app was shown problem_id=d7f3d5800286, teaching_mode=TEXTUAL,
 * before=0.2444, and a paragraph beginning "The student believes that...". Telemetry
 * addressed to a developer, and a diagnosis written about them in the third person.
 *
 * None of it is deleted, because it is the best evidence this system has that its
 * decisions are reasoned rather than random -- it just belongs somewhere a student
 * chooses to go, framed as what it is. */
function DetailView({
  events,
  progress,
}: {
  events: TutorEvent[];
  progress: Progress | null;
}) {
  const open = (progress?.skills ?? []).flatMap((s) =>
    s.misconceptions.map((m) => ({ skill: s.skill, text: m })),
  );
  const past = (progress?.skills ?? []).flatMap((s) =>
    s.overcome.map((m) => ({ skill: s.skill, text: m })),
  );

  return (
    <div className="columns">
      <section>
        <h1>Session detail</h1>
        <p className="sub" style={{ marginBottom: 18 }}>
          The tutor&apos;s working notes. These are written for diagnosis rather than as
          feedback, so they talk about you in the third person — that is why they live
          here and not on your plan.
        </p>

        <h2 style={{ margin: "18px 0 10px" }}>What it diagnosed</h2>
        {open.length === 0 && past.length === 0 && (
          <div className="note">
            Nothing diagnosed yet. Notes appear here after the tutor has seen enough of
            your work to have an opinion about it.
          </div>
        )}
        {open.map((m, i) => (
          <div className="note warn" key={`o${i}`}>
            <strong>Open · {pretty(m.skill)}</strong>
            {m.text}
          </div>
        ))}
        {past.map((m, i) => (
          <div className="note good" key={`p${i}`}>
            <strong>Resolved · {pretty(m.skill)}</strong>
            {m.text}
          </div>
        ))}
      </section>

      <ActivityPanel events={events} />
    </div>
  );
}

function ProgressView({ progress, activity }: { progress: Progress; activity: Activity }) {
  const overcome = progress.skills.flatMap((s) =>
    s.overcome.map((m) => ({ skill: s.skill, text: m })),
  );
  const active = progress.skills.flatMap((s) =>
    s.misconceptions.map((m) => ({ skill: s.skill, text: m })),
  );
  const confirmed = progress.skills.filter((s) => s.state === "completed").length;

  return (
    <div className="columns">
      <section>
        <h1>Progress</h1>

        <StudentDashboard activity={activity} />

        {/* The headline used to be an average mastery percentage, which read as "you are
            62% through the course" and sat directly beside "0 ATTEMPTS". It was the mean
            of the tutor's own estimates, most of which were priors. A count of what has
            actually been confirmed cannot be misread that way, and it agrees with the
            learning plan because both come from the same predicate. */}
        <div className="toolbar">
          <div className="stat done">
            <b>
              {confirmed}/{progress.skills.length}
            </b>
            <span>CONFIRMED</span>
          </div>
          <div className="stat">
            <b>{progress.total_attempts}</b>
            <span>ATTEMPTS</span>
          </div>
          <div className="stat maybe">
            <b>{overcome.length}</b>
            <span>OVERCOME</span>
          </div>
        </div>

        {/* The whole reason this screen exists, and for a long time the one thing it did
            not show. The engine returns mastery, confidence and attempts for every
            skill; the page rendered three aggregate numbers and a white void, so a
            student who clicked "Progress" to see how they were doing per topic learned
            nothing about any topic. */}
        <h2 style={{ margin: "10px 0 4px" }}>Where you stand</h2>
        <p className="sub" style={{ marginBottom: 14 }}>
          Weakest first. Confidence is how much evidence sits behind the estimate — a
          topic answered right once scores high and is believed very little.
        </p>

        {progress.skills.map((s) => (
          <div className="standing" key={s.skill}>
            <div className="spread">
              <b>{pretty(s.skill)}</b>
              <span className={STANDING_CHIP[s.state]}>{STANDING_LABEL[s.state]}</span>
            </div>

            <div className="bar" style={{ margin: "8px 0 6px" }}>
              <span style={{ width: `${Math.max(2, Math.min(1, s.mastery) * 100)}%` }} />
            </div>

            <p className="muted" style={{ margin: 0 }}>
              {(s.mastery * 100).toFixed(0)}% estimated · {(s.confidence * 100).toFixed(0)}%
              confidence ·{" "}
              {s.attempts === 0
                ? "not attempted yet"
                : `${s.attempts} attempt${s.attempts === 1 ? "" : "s"}`}
            </p>
          </div>
        ))}

        {/* The prose here is the diagnoser's own wording -- "The student believes that
            Python function definitions require a return type..." -- written ABOUT a
            learner for the tutor's benefit, in the third person. Reading a clinical
            write-up of yourself is a bad moment, so the sentences moved to the session
            detail view where that voice is the point. What stays is the fact, in the
            second person, which is what a student can actually act on. */}
        {(overcome.length > 0 || active.length > 0) && (
          <>
            <h2 style={{ margin: "22px 0 12px" }}>Sticking points</h2>
            {overcome.length > 0 && (
              <div className="note good">
                <strong>You have grown out of {overcome.length}</strong>
                {[...new Set(overcome.map((m) => pretty(m.skill)))].join(", ")}
              </div>
            )}
            {active.length > 0 && (
              <div className="note warn">
                <strong>Still working on</strong>
                {[...new Set(active.map((m) => pretty(m.skill)))].join(", ")} — the tutor
                is targeting these next. Its notes are in Session detail, under More.
              </div>
            )}
          </>
        )}
      </section>

      <aside className="panel">
        <div className="head">
          <h2>Recent activity</h2>
        </div>
        {progress.recent_attempts.length === 0 && (
          <div className="event plain">
            <p>
              Nothing here yet. The quick check is a probe, not an attempt — this fills
              up once you start answering real exercises, and every line shows what your
              mastery did and why.
            </p>
          </div>
        )}
        {progress.recent_attempts.map((a, i) => (
          <div className={`event ${a.outcome === "CORRECT" ? "leaf" : "butter"}`} key={i}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <span className="kind">{pretty(a.skill)}</span>
              <span className="when">
                {a.mastery_before.toFixed(2)} → {a.mastery_after.toFixed(2)}
              </span>
            </div>
            <p>{a.outcome.replace(/_/g, " ").toLowerCase()}</p>
          </div>
        ))}
      </aside>
    </div>
  );
}
