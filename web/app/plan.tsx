"use client";

/**
 * The learning plan: the prerequisite graph, drawn.
 *
 * Every card state comes from the engine. This file decides where a card sits on the
 * screen and nothing else -- it does not work out whether a skill is locked, because
 * that is a prerequisite judgement and prerequisite judgements are the whole subject of
 * the system underneath.
 */

import { useEffect, useRef, useState } from "react";
import type { Plan, PlanSkill, TutorEvent } from "@/lib/api";

const LABELS: Record<string, string> = {
  variables: "Variables",
  conditionals: "Conditionals",
  loops: "Loops",
  functions: "Functions",
  function_call_tracing: "Function Call Tracing",
  recursion: "Recursion",
  recursion_tree: "Recursion Trees",
  nested_loops: "Nested Loops",
};

const BLURBS: Record<string, string> = {
  variables: "Store a value, give it a name, and use it again later.",
  conditionals: "Make the program choose between two paths.",
  loops: "Repeat work without writing it out every time.",
  functions: "Package work up, hand it inputs, and get an answer back.",
  function_call_tracing: "Follow a value as it moves between functions.",
  recursion: "A function that solves a smaller version of its own problem.",
  recursion_tree: "Recursion that branches, and the shape that makes.",
  nested_loops: "A loop inside a loop, and what that costs.",
};

/* Exported so every screen names a skill identically. Progress spelled its own
   "Recursion Tree" against the plan's "Recursion Trees" for exactly as long as this
   lived here privately -- one student, one skill, two names. */
export const pretty = (s: string) => LABELS[s] ?? s.replace(/_/g, " ");

export function LearningPlan({
  plan,
  events,
  activeSkill,
  onStart,
  busy,
}: {
  plan: Plan;
  events: TutorEvent[];
  activeSkill: string | null;
  onStart: (skill: string) => void;
  busy: boolean;
}) {
  const [query, setQuery] = useState("");
  const gridRef = useRef<HTMLDivElement>(null);
  const [edges, setEdges] = useState<string[]>([]);

  const shown = plan.skills.filter(
    (s) =>
      !query.trim() ||
      pretty(s.skill).toLowerCase().includes(query.trim().toLowerCase()),
  );
  const unlocked = plan.counts.total - plan.counts.upcoming;

  // Draw the prerequisite edges between the cards actually on screen. Measured from
  // the DOM rather than hard-coded, so the lines stay correct when the grid reflows.
  useEffect(() => {
    const desktop = window.matchMedia("(min-width: 768px)");
    const draw = () => {
      if (!desktop.matches) {
        setEdges([]);
        return;
      }
      const grid = gridRef.current;
      if (!grid) return;
      const base = grid.getBoundingClientRect();
      const box = (skill: string) => {
        const el = grid.querySelector<HTMLElement>(`[data-skill="${skill}"]`);
        return el ? el.getBoundingClientRect() : null;
      };
      const paths: string[] = [];
      for (const item of shown) {
        const to = box(item.skill);
        if (!to) continue;
        for (const prereq of item.prerequisites) {
          const from = box(prereq);
          if (!from) continue;
          const x1 = from.right - base.left;
          const y1 = from.top - base.top + from.height / 2;
          const x2 = to.left - base.left;
          const y2 = to.top - base.top + to.height / 2;
          const mid = x1 + (x2 - x1) / 2;
          paths.push(
            x2 > x1
              ? `M ${x1} ${y1} H ${mid} V ${y2} H ${x2}`
              : `M ${x1} ${y1} H ${x1 + 16} V ${(y1 + y2) / 2} H ${x2 - 16} V ${y2} H ${x2}`,
          );
        }
      }
      setEdges(paths);
    };
    draw();
    window.addEventListener("resize", draw);
    desktop.addEventListener("change", draw);
    return () => {
      window.removeEventListener("resize", draw);
      desktop.removeEventListener("change", draw);
    };
  }, [shown.length, query, plan.student_id]);

  return (
    <div className="columns">
      <section>
        <h1>
          My Learning Plan <span aria-hidden>🎓</span>
        </h1>

        <div className="toolbar">
          <div className="search">
            <span aria-hidden>⌕</span>
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search"
              aria-label="Search skills"
            />
          </div>
          <div className="stat">
            <b>{plan.counts.total}</b>
            <span>TOTAL</span>
          </div>
          <div className="stat done">
            <b>{plan.counts.done}</b>
            <span>DONE</span>
          </div>
          <div className="stat maybe" title="Answered well once — not confirmed yet">
            <b>{plan.counts.provisional}</b>
            <span>LOOKS GOOD</span>
          </div>
          <div className="stat">
            <b>{plan.counts.upcoming}</b>
            <span>UPCOMING</span>
          </div>
        </div>

        <div className="flow-head">
          <span>
            <i aria-hidden />
            CURRICULUM FLOW
          </span>
          <span>{unlocked} of {plan.counts.total} unlocked</span>
        </div>

        <div className="plan" ref={gridRef}>
          <svg className="edges" aria-hidden>
            {edges.map((d, i) => (
              <path key={i} d={d} />
            ))}
          </svg>
          {shown.map((skill, index) => {
            const active = skill.skill === activeSkill;
            const suggested = !activeSkill && skill.skill === plan.suggested_next;
            const nextCompleted = shown[index + 1]?.state === "completed";
            return (
              <div
                className={`spine-item spine-${active ? "active" : skill.state}${
                  skill.state === "completed" ? " spine-completed" : ""
                }${skill.state === "completed" && nextCompleted ? " spine-continues" : ""}`}
                key={skill.skill}
              >
                <div className="spine-node" aria-hidden>
                  {spineGlyph(skill, active)}
                </div>
                <SkillCard
                  skill={skill}
                  active={active}
                  // Suppressed while a skill is in flight. Two cards competing for "do this
                  // next" is worse than none, and the honest next step for someone mid-topic
                  // is to finish it.
                  suggested={suggested}
                  onStart={() => onStart(skill.skill)}
                  busy={busy}
                />
              </div>
            );
          })}
        </div>
      </section>

      <ActivityPanel events={events} />
    </div>
  );
}

function spineGlyph(skill: PlanSkill, active: boolean) {
  if (active) return "▶";
  if (skill.state === "completed") return "✓";
  if (skill.state === "provisional") return "◐";
  if (skill.state === "locked") return "🔒";
  return "+";
}

function SkillCard({
  skill,
  active,
  suggested,
  onStart,
  busy,
}: {
  skill: PlanSkill;
  active: boolean;
  suggested: boolean;
  onStart: () => void;
  busy: boolean;
}) {
  const locked = skill.state === "locked";
  const done = skill.state === "completed";
  const provisional = skill.state === "provisional";
  const statusClass = done
    ? "chip done"
    : active
      ? "chip now"
      : provisional
        ? "chip maybe"
        : "chip";
  const statusLabel = done
    ? "Completed"
    : active
      ? "In progress"
      : provisional
        ? "Looks good ◐"
        : locked
          ? "Upcoming"
          : "Ready";
  const statusTitle = provisional ? "Answered well once — one more to be sure" : undefined;
  return (
    <article
      className={`card${active ? " active" : ""}${locked ? " locked" : ""}${
        suggested ? " suggested" : ""
      }`}
      data-skill={skill.skill}
    >
      {/* The check ends by saying "Start here: functions" and then hands over a grid of
          eight cards. Until this existed, the suggestion lived only in a `title`
          attribute -- invisible on a phone, invisible to a screen reader that is not
          hovering, and invisible to anyone who simply looks. The one instruction the
          student was given had nowhere to land. Same words as the summary screen, on
          purpose: they are meant to be recognised, not re-read. */}
      {suggested && <p className="flag">Start here</p>}
      {active && <p className="flag active-now">Active now</p>}

      <div className="top">
        <h3>{pretty(skill.skill)}</h3>
        <span className={`${statusClass} status-mobile`} title={statusTitle}>
          {statusLabel}
        </span>
        {active ? (
          <button className="play top-play" onClick={onStart} disabled={busy} aria-label="Continue">
            ▶
          </button>
        ) : (
          <div className={`dot${locked ? " lock" : ""}`} aria-hidden>
            {done ? "✓" : provisional ? "◐" : locked ? "🔒" : "＋"}
          </div>
        )}
      </div>

      <p className="desc">{BLURBS[skill.skill] ?? "A skill in this course."}</p>

      {/* Locked is not a wall, it is an explanation. Saying which prerequisite is
          blocking turns "you can't" into "do this first". */}
      {locked && (
        <p className="muted" style={{ marginTop: -6, marginBottom: 12 }}>
          Waiting on {skill.blocked_by.map(pretty).join(", ")}
        </p>
      )}

      {provisional && (
        <p className="muted" style={{ marginTop: -6, marginBottom: 12 }}>
          You got this right — one more to be sure
        </p>
      )}

      <div className="bar" aria-hidden>
        <span style={{ width: `${Math.max(2, Math.min(1, skill.mastery) * 100)}%` }} />
      </div>

      <div className="foot" style={{ marginTop: 12 }}>
        {/* One right answer is evidence, not a finished topic. Saying so is the whole
           difference between a tutor and a progress bar. */}
        <span className={`${statusClass} status-desktop`} title={statusTitle}>
          {statusLabel}
        </span>

        <div className="row skill-action" style={{ gap: 6 }}>
          <span className="muted">{(skill.mastery * 100).toFixed(0)}% mastery</span>
          {active && (
            <button className="play mobile-play" onClick={onStart} disabled={busy} aria-label="Continue">
              ▶
            </button>
          )}
          {!locked && !active && (
            <button
              className={`iconbtn solid${suggested ? " go" : ""}`}
              onClick={onStart}
              disabled={busy}
              aria-label={
                suggested
                  ? `Start ${pretty(skill.skill)} — suggested next`
                  : `Start ${pretty(skill.skill)}`
              }
            >
              ▸
            </button>
          )}
        </div>
      </div>
    </article>
  );
}

/* The right-hand column. The design showed scheduled webinars and lessons; this system
   has no calendar and inventing one would be the first dishonest thing in it. What it
   does have is better: every decision the tutor just made, and why. */
const TONE: Record<string, string> = {
  diagnostic: "sky",
  plan: "lilac",
  retrieval: "sky",
  generated: "lilac",
  execution: "plain",
  misconception: "butter",
  mastery: "leaf",
  adaptation: "butter",
  guard_override: "butter",
  prereq_redirect: "lilac",
  prereq_return: "leaf",
  recovery: "plain",
  session_end: "leaf",
};

const ICON: Record<string, string> = {
  diagnostic: "🔍", plan: "🗺", retrieval: "📚", generated: "✎", execution: "⚙",
  misconception: "🧠", mastery: "📈", adaptation: "🧭", guard_override: "🛡",
  prereq_redirect: "↩", prereq_return: "↪", recovery: "🩹", session_end: "🏁",
};

function ActivityPanel({ events }: { events: TutorEvent[] }) {
  const recent = [...events].reverse().slice(0, 8);
  return (
    <aside className="panel">
      <div className="head">
        <h2>
          Why it did that <span aria-hidden>🧐</span>
        </h2>
      </div>

      {recent.length === 0 && (
        <div className="event plain">
          <p>
            Start a skill and every decision the tutor makes appears here, with its
            reason — including the ones where it overrules its own model.
          </p>
        </div>
      )}

      {recent.map((event, i) => (
        <div className={`event ${TONE[event.type] ?? "plain"}`} key={i}>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <span className="kind">
              <span className="badge" aria-hidden>{ICON[event.type] ?? "•"}</span>
              {event.type.replace(/_/g, " ")}
            </span>
            <span className="when">{event.node}</span>
          </div>
          <p>
            {event.reason ??
              Object.entries(event.payload)
                .slice(0, 3)
                .map(([k, v]) => `${k}=${String(v)}`)
                .join(" · ")}
          </p>
        </div>
      ))}
    </aside>
  );
}
