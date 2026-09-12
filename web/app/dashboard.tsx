"use client";

import type { Activity } from "@/lib/api";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const HOURS = Array.from({ length: 24 }, (_, hour) => hour);
// Each heatmap column is 18 px including its gap. Two columns leave enough room for
// every three-letter month name at the rendered 10 px size.
const MIN_MONTH_LABEL_COLUMNS = 2;

function startOfLocalDay(date: Date) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

function addDays(date: Date, days: number) {
  const next = new Date(date);
  next.setDate(next.getDate() + days);
  return next;
}

function mondayStart(date: Date) {
  return addDays(startOfLocalDay(date), -((date.getDay() + 6) % 7));
}

function shortDate(date: Date) {
  return new Intl.DateTimeFormat(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
  }).format(date);
}

function monthName(date: Date) {
  return new Intl.DateTimeFormat(undefined, { month: "short" }).format(date);
}

function attemptText(count: number) {
  return `${count} attempt${count === 1 ? "" : "s"}`;
}

function buildMonthLabels(weeks: Date[][]) {
  const labels = weeks.map((week, index) => {
    const firstDay = week[0];
    const previous = index > 0 ? weeks[index - 1][0] : null;
    return !previous || previous.getMonth() !== firstDay.getMonth()
      ? monthName(firstDay)
      : "";
  });
  let previousLabel = -MIN_MONTH_LABEL_COLUMNS;
  labels.forEach((label, index) => {
    if (!label) return;
    if (index - previousLabel < MIN_MONTH_LABEL_COLUMNS) {
      // Prefer the newer month when the range starts in the final week of the old one.
      labels[previousLabel] = "";
    }
    previousLabel = index;
  });
  return labels;
}

function intensity(count: number) {
  if (count <= 0) return 0;
  if (count === 1) return 1;
  if (count === 2) return 2;
  if (count <= 4) return 3;
  return 4;
}

function buildLocalBuckets(activity: Activity) {
  const byDay = new Map<string, number>();
  const byHour = new Map<number, number>();

  for (const attempt of activity.attempts) {
    const at = new Date(attempt.at);
    byDay.set(at.toDateString(), (byDay.get(at.toDateString()) ?? 0) + 1);
    byHour.set(at.getHours(), (byHour.get(at.getHours()) ?? 0) + 1);
  }

  return { byDay, byHour };
}

function currentStreak(byDay: Map<string, number>) {
  let streak = 0;
  let cursor = startOfLocalDay(new Date());
  while ((byDay.get(cursor.toDateString()) ?? 0) > 0) {
    streak += 1;
    cursor = addDays(cursor, -1);
  }
  return streak;
}

function bestDay(byDay: Map<string, number>) {
  let best: { key: string; count: number } | null = null;
  for (const [key, count] of byDay) {
    if (!best || count > best.count) best = { key, count };
  }
  if (!best) return { count: 0, label: "None yet" };
  return { count: best.count, label: shortDate(new Date(best.key)) };
}

export function StudentDashboard({ activity }: { activity: Activity }) {
  const { byDay, byHour } = buildLocalBuckets(activity);
  const today = startOfLocalDay(new Date());
  const firstWeek = addDays(mondayStart(today), -15 * 7);
  const weeks = Array.from({ length: 16 }, (_, week) =>
    Array.from({ length: 7 }, (_, day) => addDays(firstWeek, week * 7 + day)),
  );
  const monthLabels = buildMonthLabels(weeks);
  const hourCounts = HOURS.map((hour) => byHour.get(hour) ?? 0);
  const maxHour = Math.max(0, ...hourCounts);
  const streak = currentStreak(byDay);
  const best = bestDay(byDay);
  const hasActivity = activity.attempts.length > 0;

  return (
    <section className="dashboard" aria-labelledby="activity-title">
      <div className="dashboard-head">
        <div>
          <h2 id="activity-title">Study activity</h2>
          <p className="sub">Local-time patterns from your recent exercise attempts.</p>
        </div>
      </div>

      <div className="dashboard-stats">
        <div className="stat">
          <b>{activity.total}</b>
          <span>ATTEMPTS</span>
        </div>
        <div className="stat done">
          <b>{streak}</b>
          <span>DAY STREAK</span>
        </div>
        <div className="stat maybe">
          <b>{best.count}</b>
          <span>BEST DAY</span>
        </div>
      </div>
      <p className="best-day muted">{best.label}</p>

      {!hasActivity ? (
        <div className="empty-activity">
          No study activity yet. This fills in as you answer exercises.
        </div>
      ) : (
        <>
          <div className="heatmap-scroll" role="region" aria-label="Daily attempt heatmap">
            <div className="heatmap" role="grid" aria-label="Attempts by local day">
              <div className="heatmap-months" aria-hidden>
                <span />
                {monthLabels.map((label, index) => (
                  <span key={index}>{label}</span>
                ))}
              </div>
              <div className="heatmap-body">
                <div className="heatmap-days" aria-hidden>
                  {WEEKDAYS.map((weekday) => (
                    <span key={weekday}>{weekday}</span>
                  ))}
                </div>
                {weeks.map((week, weekIndex) => (
                  <div className="heatmap-week" role="row" key={weekIndex}>
                    {week.map((day) => {
                      const count = byDay.get(day.toDateString()) ?? 0;
                      const label = `${attemptText(count)} on ${shortDate(day)}`;
                      return (
                        <span
                          className={`heat-cell heat-${intensity(count)}`}
                          role="gridcell"
                          aria-label={label}
                          title={label}
                          key={day.toDateString()}
                        />
                      );
                    })}
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="hour-strip" aria-label="Attempts by local hour">
            {HOURS.map((hour) => {
              const count = hourCounts[hour];
              const height = maxHour ? Math.max(4, Math.round((count / maxHour) * 54)) : 0;
              return (
                <div
                  className="hour-column"
                  aria-label={`${attemptText(count)} around ${hour}:00 local time`}
                  title={`${attemptText(count)} around ${hour}:00`}
                  key={hour}
                >
                  <span
                    className={`hour-bar heat-${intensity(count)}`}
                    style={{ height }}
                  />
                  {[0, 6, 12, 18].includes(hour) && <small>{hour}</small>}
                </div>
              );
            })}
          </div>
        </>
      )}

      <p className="activity-note muted">
        Activity is recorded per attempt. The quick check is a probe rather than an
        attempt, so it does not appear here.
      </p>
    </section>
  );
}
