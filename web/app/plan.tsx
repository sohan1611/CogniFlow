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

const pretty = (s: string) => LABELS[s] ?? s.replace(/_/g, " ");

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

  // Draw the prerequisite edges between the cards actually on screen. Measured from
  // the DOM rather than hard-coded, so the lines stay correct when the grid reflows.
  useEffect(() => {
    const draw = () => {
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
    return () => window.removeEventListener("resize", draw);
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
          <div className="stat">
            <b>{plan.counts.upcoming}</b>
            <span>UPCOMING</span>
          </div>
        </div>

        <div className="plan" ref={gridRef}>
          <svg className="edges" aria-hidden>
            {edges.map((d, i) => (
              <path key={i} d={d} />
            ))}
          </svg>
          {shown.map((skill) => (
            <SkillCard
              key={skill.skill}
              skill={skill}
              active={skill.skill === activeSkill}
              suggested={skill.skill === plan.suggested_next}
              onStart={() => onStart(skill.skill)}
              busy={busy}
            />
          ))}
        </div>
      </section>

      <ActivityPanel events={events} />
    </div>
  );
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
  return (
    <article
      className={`card${active ? " active" : ""}${locked ? " locked" : ""}`}
      data-skill={skill.skill}
    >
      <div className="top">
        <h3>{pretty(skill.skill)}</h3>
        {active ? (
          <button className="play" onClick={onStart} disabled={busy} aria-label="Continue">
            ▶
          </button>
        ) : (
          <div className={`dot${locked ? " lock" : ""}`} aria-hidden>
            {done ? "✓" : locked ? "🔒" : "＋"}
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

      <div className="bar" aria-hidden>
        <span style={{ width: `${Math.max(2, Math.min(1, skill.mastery) * 100)}%` }} />
      </div>

      <div className="foot" style={{ marginTop: 12 }}>
        {done ? (
          <span className="chip done">Completed 👏</span>
        ) : active ? (
          <span className="chip now">In progress</span>
        ) : locked ? (
          <span className="chip">Upcoming ⏱</span>
        ) : (
          <span className="chip">Ready</span>
        )}

        <div className="row" style={{ gap: 6 }}>
          <span className="muted">{(skill.mastery * 100).toFixed(0)}%</span>
          {!locked && !active && (
            <button
              className="iconbtn solid"
              onClick={onStart}
              disabled={busy}
              aria-label={`Start ${pretty(skill.skill)}`}
              title={suggested ? "Suggested next" : "Start this skill"}
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
