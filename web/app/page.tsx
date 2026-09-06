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
  type DiagnosticStep,
  type Health,
  type Plan,
  type Progress,
  type TutorView,
} from "@/lib/api";
import { LearningPlan } from "./plan";
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
      if (next === "progress") setProgress(await api.progress(id));
      swap(() => setTab(next));
    });

  // -------------------------------------------------------------- render
  return (
    <Shell tab={tab} onTab={changeTab} name={stage === "name" ? null : name} sweeping={sweeping}>
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
        <div className="note warn">
          <strong>Running on built-in templates</strong>
          No model provider is configured, so exercise wording is templated. Every
          tutoring decision below is still computed exactly as it would be live.
        </div>
      )}
      {error && <p className="err">{error}</p>}

      {stage === "name" && (
        <div style={{ maxWidth: 460, margin: "8vh auto 0" }}>
          <h1>Let&apos;s begin</h1>
          <p className="sub" style={{ marginBottom: 22 }}>
            A tutor that changes its own objective when it works out <em>why</em> you are
            failing.
          </p>
          <label htmlFor="nm">What should I call you?</label>
          <input
            id="nm"
            type="text"
            value={name}
            placeholder="e.g. Aarav"
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && name.trim() && begin()}
          />
          <p className="muted" style={{ margin: ".7rem 0 1.2rem" }}>
            Used to remember what you know between visits. Nothing else is stored.
          </p>
          <button
            className="btn"
            onClick={begin}
            disabled={busy || !name.trim() || reachable !== true}
          >
            {busy
              ? "Starting…"
              : reachable === false
                ? "Engine offline"
                : reachable === null
                  ? "Waking the engine…"
                  : "Start"}
          </button>
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
              <h3>{step.skill.replace(/_/g, " ")}</h3>
              <span className="chip">Question {step.answered + 1}</span>
            </div>
            <p className="desc" style={{ whiteSpace: "pre-wrap" }}>{step.prompt}</p>
            <textarea value={code} onChange={(e) => setCode(e.target.value)} spellCheck={false} />
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
              {step.weakest_skill?.replace(/_/g, " ") ?? "nothing — you are ahead of this course"}
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
          events={view?.events ?? []}
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

      {stage === "app" && tab === "progress" && progress && (
        <ProgressView progress={progress} />
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
            <p className="desc" style={{ whiteSpace: "pre-wrap" }}>{view.problem.prompt}</p>
            {view.problem.expected_output && (
              <p className="muted">
                Expected output: <code>{view.problem.expected_output}</code>
              </p>
            )}
            <textarea value={code} onChange={(e) => setCode(e.target.value)} spellCheck={false} />
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
                  {skill.replace(/_/g, " ")}
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

function ProgressView({ progress }: { progress: Progress }) {
  const overcome = progress.skills.flatMap((s) =>
    s.overcome.map((m) => ({ skill: s.skill, text: m })),
  );
  const active = progress.skills.flatMap((s) =>
    s.misconceptions.map((m) => ({ skill: s.skill, text: m })),
  );
  return (
    <div className="columns">
      <section>
        <h1>Progress</h1>
        <div className="toolbar">
          <div className="stat">
            <b>{(progress.overall_mastery * 100).toFixed(0)}%</b>
            <span>OVERALL</span>
          </div>
          <div className="stat">
            <b>{progress.total_attempts}</b>
            <span>ATTEMPTS</span>
          </div>
          <div className="stat done">
            <b>{overcome.length}</b>
            <span>OVERCOME</span>
          </div>
        </div>

        {(overcome.length > 0 || active.length > 0) && (
          <>
            <h2 style={{ margin: "10px 0 12px" }}>Misconceptions</h2>
            {overcome.map((m, i) => (
              <div className="note good" key={`o${i}`}>
                <strong>Overcome · {m.skill.replace(/_/g, " ")}</strong>
                {m.text}
              </div>
            ))}
            {active.map((m, i) => (
              <div className="note warn" key={`a${i}`}>
                <strong>Still working on · {m.skill.replace(/_/g, " ")}</strong>
                {m.text}
              </div>
            ))}
          </>
        )}
      </section>

      <aside className="panel">
        <div className="head">
          <h2>Recent activity</h2>
        </div>
        {progress.recent_attempts.length === 0 && (
          <div className="event plain">
            <p>No attempts recorded yet.</p>
          </div>
        )}
        {progress.recent_attempts.map((a, i) => (
          <div className={`event ${a.outcome === "CORRECT" ? "leaf" : "butter"}`} key={i}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <span className="kind">{a.skill.replace(/_/g, " ")}</span>
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
