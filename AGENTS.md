# CogniFlow — rules for any AI agent working in this repository

Read this before making any change. It applies to Claude Code, Codex, and any other
assistant. These are not style preferences; the first one is a hard project rule.

---

## RULE 1 (HARD) — the contributor list stays exactly two humans

This repository has **two contributors and only two**: the owner and one collaborator.
Nothing else may ever appear in GitHub's contributor list.

**Forbidden, without exception:**

- ❌ **`Co-Authored-By:` trailers of any kind.** No `Co-Authored-By: Claude`, no Codex,
  no bot, no assistant. Do not add one "just this once". This is the single most common
  way an AI ends up in a contributor list, and it is silent and permanent once pushed.
- ❌ **Dependabot.** Do not create `.github/dependabot.yml`. Do not enable it in repo
  settings. If GitHub offers a Dependabot security-update PR, it must be dismissed or
  applied manually by a human — never merged as a Dependabot-authored commit.
- ❌ **Any other GitHub App or bot** that authors commits or PRs (renovate,
  pre-commit.ci, allcontributors, release bots, etc.).
- ❌ Changing `user.name` / `user.email` away from a human contributor's identity.

**Required:**

- ✅ Every commit is authored by a human contributor's git identity.
- ✅ Commit messages describe the change and stop there. No attribution footer,
  no "generated with", no emoji signature.
- ✅ If a workflow needs to commit (it should not), it does not run here.

**Why it matters:** the contributor list is public evidence of authorship for a
hackathon submission judged partly on the team's own work (rulebook §10, originality
and fair play). A bot in that list is a question the team should never have to answer.

**Before any push, run:**

```bash
.venv/Scripts/python.exe scripts/check_contributors.py
```

Exits 0 when clean, 1 on any violation, and prints exactly what is wrong.

Do **not** substitute a naive `git log | grep -i claude`. Our commit messages legitimately
discuss Claude and Codex as *models and tools*, so that grep false-positives on ordinary
technical prose - and a check that cries wolf is a check people learn to ignore. The
script inspects the fields that actually determine authorship: author and committer
identity, attribution trailers, and tracked bot config files.

It is covered by `tests/test_contributors.py`, which builds throwaway repositories and
runs the real script against real history: a clean commit whose message mentions Claude
passes, while a `Co-Authored-By:` trailer, a `dependabot[bot]` author and a tracked
`dependabot.yml` are each caught.

One case is there for a specific reason. The script decoded git's UTF-8 output with the
platform default -- cp1252 on Windows -- so the first commit message containing an emoji
killed the reader thread and the check died on an AttributeError. It reported FAILED,
which is exactly what a real violation reports, and the two were indistinguishable at a
glance. **A broken check here is worse than no check**, because this one is trusted
without being re-read. If it ever fails, read the output before assuming a violation.

---

## RULE 2 — no secrets, ever

API keys live in `.env`, which is gitignored. `.env.example` holds key *names* with
empty values. Rulebook §6 forbids committed credentials and §13 makes it a
disqualification path. Run the secret scan before every push.

---

## RULE 3 — the safety invariant

`StudentOutcome` and `SystemFault` are disjoint types. Mastery scores may only ever be
changed by `StudentOutcome`. An infrastructure failure (sandbox crash, LLM timeout,
malformed output) must be **structurally incapable** of lowering a student's mastery —
enforced by the type system, not by a conditional someone has to notice in review.

If you find yourself writing a code path where a `SystemFault` reaches
`app/mastery/bkt.py::update`, the design is wrong, not the guard.

---

## RULE 4 — deterministic where it matters

Routing, mastery arithmetic, prerequisite selection, and limit enforcement are
**deterministic and unit-tested**. The LLM proposes; `app/mastery/guard.py` disposes.
Do not move a routing decision into a prompt because it is easier.

Do not add an LLM call where arithmetic is already correct and free.

---

## RULE 5 — no placeholder code in core paths

No `TODO`, no `FIXME`, no `pass  # implement later`, no fake mock standing in for real
prototype behavior. If something cannot be finished, say so explicitly rather than
leaving a stub that looks finished.
