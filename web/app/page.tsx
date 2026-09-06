"use client";

/**
 * The whole student experience, as a small state machine.
 *
 *   name  ->  diagnostic  ->  tutoring  ->  progress
 *
 * Every transition is driven by what the engine returns, never by a decision made
 * here. This component knows how to draw a problem; it does not know how a problem is
 * chosen, and it must not learn.
 */

import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  api,
  type DiagnosticStep,
  type Health,
  type Progress,
  type TutorView,
} from "@/lib/api";

type Stage = "name" | "diagnostic" | "tutoring" | "progress";

export default function Page() {
  const [stage, setStage] = useState<Stage>("name");
  const [name, setName] = useState("");
  const [studentId, setStudentId] = useState("");
  const [health, setHealth] = useState<Health | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [step, setStep] = useState<DiagnosticStep | null>(null);
  const [view, setView] = useState<TutorView | null>(null);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [code, setCode] = useState("");

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
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

  // ------------------------------------------------------------- actions
  const begin = () =>
    guard(async () => {
      const session = await api.startSession(name);
      setStudentId(session.student_id);
      if (session.needs_diagnostic) {
        setStep(await api.diagnosticQuestion(session.student_id));
        setCode("");
        setStage("diagnostic");
      } else {
        const next = await api.beginTutoring(session.student_id, name);
        setView(next);
        setCode(next.problem?.starter_code ?? "");
        setStage("tutoring");
      }
    });

  const answerDiagnostic = (submitted: string) =>
    guard(async () => {
      if (!step || step.complete) return;
      await api.answerDiagnostic(studentId, step.skill, submitted);
      const next = await api.diagnosticQuestion(studentId);
      setStep(next);
      setCode(next.complete ? "" : next.starter_code);
    });

  const startTutoring = () =>
    guard(async () => {
      const next = await api.beginTutoring(studentId, name);
      setView(next);
      setCode(next.problem?.starter_code ?? "");
      setStage("tutoring");
    });

  const submit = () =>
    guard(async () => {
      const next = await api.submit(studentId, code);
      setView(next);
      setCode(next.problem?.starter_code ?? "");
    });

  const showProgress = () =>
    guard(async () => {
      setProgress(await api.progress(studentId));
      setStage("progress");
    });

  // ------------------------------------------------------------- render
  return (
    <>
      <h1>CogniFlow</h1>
      <p className="lede">
        A tutor that changes its own objective when it works out <em>why</em> you are
        failing.
      </p>

      {health && health.generation !== "live" && (
        <div className="note warn">
          <strong>Running on built-in templates</strong>
          No model provider is configured, so exercise wording is templated. Every
          tutoring decision below is still computed exactly as it would be live.
        </div>
      )}
      {error && <p className="err">{error}</p>}

      {stage === "name" && (
        <div className="card">
          <label htmlFor="name">What should I call you?</label>
          <input
            id="name"
            type="text"
            value={name}
            placeholder="e.g. Aarav"
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && name.trim() && begin()}
          />
          <p className="muted" style={{ margin: ".6rem 0 1rem" }}>
            Used to remember what you know between visits. Nothing else is stored.
          </p>
          <button onClick={begin} disabled={busy || !name.trim()}>
            {busy ? "Starting…" : "Start"}
          </button>
        </div>
      )}

      {stage === "diagnostic" && step && !step.complete && (
        <div className="card">
          <div className="spread">
            <h2 style={{ margin: 0 }}>Quick check</h2>
            <span className="pill">{step.skill}</span>
          </div>
          <p className="muted">
            No grade here — getting one wrong just means we start there.
            {Object.keys(step.skipped).length > 0 &&
              ` ${Object.keys(step.skipped).length} question(s) already skipped, because
                you showed me the answer by missing what they build on.`}
          </p>
          <p style={{ whiteSpace: "pre-wrap" }}>{step.prompt}</p>
          <textarea value={code} onChange={(e) => setCode(e.target.value)} spellCheck={false} />
          <div className="row" style={{ marginTop: ".7rem" }}>
            <button onClick={() => answerDiagnostic(code)} disabled={busy}>
              {busy ? "Checking…" : "Submit"}
            </button>
            <button
              className="secondary"
              onClick={() => answerDiagnostic("")}
              disabled={busy}
            >
              I don&apos;t know this one
            </button>
          </div>
        </div>
      )}

      {stage === "diagnostic" && step?.complete && (
        <div className="card">
          <h2 style={{ marginTop: 0 }}>Here is what I found</h2>
          <p>
            <strong>Start here:</strong>{" "}
            {step.weakest_skill ?? "nothing — you are ahead of this course"}
            {step.missing_prerequisites.length > 0 && (
              <>
                <br />
                <strong>Gaps underneath it:</strong>{" "}
                {step.missing_prerequisites.join(", ")}
              </>
            )}
            <br />
            <span className="muted">
              Confidence in this picture: {(step.confidence * 100).toFixed(0)}%
            </span>
          </p>
          <MasteryList mastery={step.mastery} highlight={step.weakest_skill} />
          <button onClick={startTutoring} disabled={busy} style={{ marginTop: ".8rem" }}>
            Start learning
          </button>
        </div>
      )}

      {stage === "tutoring" && view && <Tutor view={view} code={code} setCode={setCode} onSubmit={submit} onProgress={showProgress} busy={busy} />}

      {stage === "progress" && progress && (
        <ProgressPanel progress={progress} onBack={() => setStage("tutoring")} />
      )}
    </>
  );
}

function MasteryList({
  mastery,
  highlight,
}: {
  mastery: Record<string, number>;
  highlight?: string | null;
}) {
  const rows = Object.entries(mastery).sort((a, b) => a[1] - b[1]);
  return (
    <div>
      {rows.map(([skill, value]) => (
        <div className="skill" key={skill}>
          <div className="spread">
            <span style={{ fontWeight: skill === highlight ? 700 : 400 }}>{skill}</span>
            <span className="muted">{value.toFixed(2)}</span>
          </div>
          <div className="bar">
            <span style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }} />
          </div>
        </div>
      ))}
    </div>
  );
}

function Tutor({
  view,
  code,
  setCode,
  onSubmit,
  onProgress,
  busy,
}: {
  view: TutorView;
  code: string;
  setCode: (v: string) => void;
  onSubmit: () => void;
  onProgress: () => void;
  busy: boolean;
}) {
  const fb = view.feedback;
  return (
    <>
      {/* Our failure is never shown as the student's mistake. */}
      {fb?.was_our_fault && (
        <div className="note ours">
          <strong>Something on our side went wrong</strong>
          Your submission and your progress have been preserved, and nothing was counted
          against you.
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

      {/* The redirect, explained. Without this it reads as the tutor changing the
          subject for no reason -- which is the opposite of the point. */}
      {view.returning_to && view.returning_to !== view.target_skill && (
        <div className="note">
          <strong>Let&apos;s back up for a moment</strong>
          We&apos;re working on <b>{view.target_skill}</b> first, then going straight back
          to <b>{view.returning_to}</b> — that is still what you came here for, and it has
          not been forgotten.
        </div>
      )}

      {view.problem && view.awaiting_student ? (
        <div className="card">
          <div className="spread">
            <h2 style={{ margin: 0 }}>{view.problem.title}</h2>
            <span className="pill">{view.difficulty}</span>
          </div>
          <p style={{ whiteSpace: "pre-wrap" }}>{view.problem.prompt}</p>
          {view.problem.expected_output && (
            <p className="muted">
              Expected output: <code>{view.problem.expected_output}</code>
            </p>
          )}
          <textarea value={code} onChange={(e) => setCode(e.target.value)} spellCheck={false} />
          <div className="row" style={{ marginTop: ".7rem" }}>
            <button onClick={onSubmit} disabled={busy}>
              {busy ? "Running…" : "Submit"}
            </button>
            <button className="secondary" onClick={onProgress} disabled={busy}>
              My progress
            </button>
          </div>
          {view.problem.grounded_in.length > 0 && (
            <p className="muted" style={{ marginTop: ".8rem", marginBottom: 0 }}>
              Based on: {view.problem.grounded_in.join(", ")}
            </p>
          )}
        </div>
      ) : (
        <div className="card">
          <h2 style={{ marginTop: 0 }}>Session {view.session_status ?? "finished"}</h2>
          {view.recommended_next && (
            <p>
              <strong>Recommended next:</strong> <code>{view.recommended_next}</code>
            </p>
          )}
          <button className="secondary" onClick={onProgress}>
            My progress
          </button>
        </div>
      )}

      <h2>What the tutor believes</h2>
      <div className="card">
        <MasteryList mastery={view.mastery} highlight={view.target_skill} />
      </div>

      <h2>Why it did that</h2>
      <div className="card events">
        {view.events.slice(-12).map((event, i) => (
          <div key={i}>
            <b>{event.type}</b> {event.node}
            {event.reason && <> — {event.reason}</>}
          </div>
        ))}
      </div>
    </>
  );
}

function ProgressPanel({
  progress,
  onBack,
}: {
  progress: Progress;
  onBack: () => void;
}) {
  const overcome = progress.skills.flatMap((s) =>
    s.overcome.map((m) => ({ skill: s.skill, text: m })),
  );
  const active = progress.skills.flatMap((s) =>
    s.misconceptions.map((m) => ({ skill: s.skill, text: m })),
  );
  return (
    <>
      <div className="card">
        <div className="spread">
          <h2 style={{ margin: 0 }}>Progress</h2>
          <span className="muted">
            {(progress.overall_mastery * 100).toFixed(0)}% overall ·{" "}
            {progress.total_attempts} attempts
          </span>
        </div>
      </div>

      {(overcome.length > 0 || active.length > 0) && (
        <>
          <h2>Misconceptions</h2>
          <div className="card">
            {overcome.map((m, i) => (
              <div className="note good" key={`o${i}`}>
                <strong>Overcome · {m.skill}</strong>
                {m.text}
              </div>
            ))}
            {active.map((m, i) => (
              <div className="note warn" key={`a${i}`}>
                <strong>Still working on · {m.skill}</strong>
                {m.text}
              </div>
            ))}
          </div>
        </>
      )}

      <h2>Recent activity</h2>
      <div className="card events">
        {progress.recent_attempts.length === 0 && (
          <div>No attempts recorded yet.</div>
        )}
        {progress.recent_attempts.map((a, i) => (
          <div key={i}>
            <b>{a.skill}</b> {a.outcome} — {a.mastery_before.toFixed(2)} →{" "}
            {a.mastery_after.toFixed(2)}
          </div>
        ))}
      </div>

      <button className="secondary" onClick={onBack} style={{ marginTop: "1rem" }}>
        Back to learning
      </button>
    </>
  );
}
