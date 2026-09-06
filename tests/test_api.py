"""The HTTP API.

These assert the CONTRACT a frontend depends on, not the tutoring behaviour -- that is
covered by the graph tests, and duplicating it here would just make both harder to
change. What matters is that the fields a client draws from keep existing and keep
meaning what they mean.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.main import SESSIONS, app
from app.config.settings import get_settings
from app.mastery.policy import MASTERY_THRESHOLD, is_mastered


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    """A client whose writes land in a temporary database, never data/cogniflow.db."""
    import app.api.main as api
    from app.services.student_store import StudentStore

    db = tmp_path / "api.db"
    monkeypatch.setattr(api, "StudentStore", lambda *a, **k: StudentStore(db))
    SESSIONS.clear()
    return TestClient(app)


def test_health_reports_whether_generation_is_live(client: TestClient) -> None:
    """A frontend that cannot tell degraded from healthy will present a template as
    though a model wrote it."""
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["generation"] in ("live", "deterministic-templates")
    assert isinstance(body["providers"], list)


def test_skills_exposes_the_prerequisite_graph(client: TestClient) -> None:
    """The graph is the thing worth drawing; a flat score list is not."""
    body = client.get("/skills").json()
    skills = {s["skill"]: s for s in body["skills"]}
    assert "recursion" in skills
    assert "functions" in skills["recursion"]["prerequisites"]
    assert "recursion" in skills["functions"]["unlocks"]
    assert 0 < body["mastery_threshold"] < 1


def test_a_new_student_is_told_they_need_diagnosing(client: TestClient) -> None:
    body = client.post("/session", json={"name": "Aarav"}).json()
    assert body["student_id"] == "aarav"
    assert body["returning"] is False
    assert body["needs_diagnostic"] is True


def test_a_returning_student_is_not_re_diagnosed(client: TestClient) -> None:
    client.post("/session", json={"name": "Aarav"})
    again = client.post("/session", json={"name": "Aarav"}).json()
    assert again["returning"] is True
    assert again["needs_diagnostic"] is False


def test_a_name_with_no_usable_characters_is_rejected(client: TestClient) -> None:
    """It would otherwise become an empty primary key shared by every such student."""
    assert client.post("/session", json={"name": "!!!"}).status_code == 422


def test_acting_without_a_session_is_a_clear_404(client: TestClient) -> None:
    """A frontend must be able to distinguish 'no session' from 'broken server'."""
    response = client.get("/session/nobody")
    assert response.status_code == 404
    assert "session" in response.json()["detail"].lower()


def test_diagnostic_asks_foundations_first(client: TestClient) -> None:
    client.post("/session", json={"name": "Aarav"})
    question = client.get("/session/aarav/diagnostic").json()
    assert question["complete"] is False
    assert question["skill"] == "variables", "a diagnostic must start at the root"
    assert question["prompt"]


def test_answering_the_wrong_question_is_rejected(client: TestClient) -> None:
    """Guards against a client racing ahead of the adaptive order."""
    client.post("/session", json={"name": "Aarav"})
    client.get("/session/aarav/diagnostic")
    response = client.post(
        "/session/aarav/diagnostic", json={"skill": "recursion", "code": "print(1)"}
    )
    assert response.status_code == 409


def test_diagnostic_prunes_downstream_skills_over_http(client: TestClient) -> None:
    """The adaptive behaviour must survive serialisation, not just exist in Python."""
    client.post("/session", json={"name": "Aarav"})
    asked = []
    while True:
        question = client.get("/session/aarav/diagnostic").json()
        if question["complete"]:
            break
        asked.append(question["skill"])
        # Fail functions, pass everything else.
        code = "print('nope')" if question["skill"] == "functions" else _solution(question["skill"])
        client.post(
            "/session/aarav/diagnostic", json={"skill": question["skill"], "code": code}
        )
    assert "functions" in asked
    assert "recursion" not in asked, "recursion was asked despite functions failing"


def test_progress_is_readable_without_an_active_session(client: TestClient) -> None:
    """The dashboard is durable state, not session state."""
    client.post("/session", json={"name": "Aarav"})
    body = client.get("/student/aarav/progress").json()
    assert body["student_id"] == "aarav"
    assert body["skills"], "a seeded student has skills"
    assert "overcome" in body["skills"][0], "resolved misconceptions must be exposed"
    assert body["total_attempts"] == 0


def test_progress_for_an_unknown_student_is_404(client: TestClient) -> None:
    assert client.get("/student/ghost/progress").status_code == 404


def _solution(skill: str) -> str:
    return {
        "variables": "x = 7\nx = x + 3\nprint(x)",
        "conditionals": "x = 9\nif x > 5:\n    print('big')\nelse:\n    print('small')",
        "loops": "t = 0\nfor i in range(1, 5):\n    t += i\nprint(t)",
        "nested_loops": "c = 0\nfor i in range(1,4):\n    for j in range(1,4):\n        c += 1\nprint(c)",
    }.get(skill, "print('unknown')")


def test_plan_states_come_from_the_engine_not_the_client(client: TestClient) -> None:
    """Whether a skill is locked is a prerequisite judgement, and this system exists to
    make prerequisite judgements. A client recomputing it would be a second, silently
    diverging implementation of the one thing that must not have two.
    """
    client.post("/session", json={"name": "Aarav"})
    body = client.get("/student/aarav/plan").json()

    states = {s["skill"]: s for s in body["skills"]}
    assert set(states) == {s["skill"] for s in client.get("/skills").json()["skills"]}
    for item in states.values():
        assert item["state"] in {"completed", "locked", "available"}
        if item["state"] == "locked":
            assert item["blocked_by"], "a locked skill must say what is blocking it"
        if item["state"] == "available":
            assert not item["blocked_by"]

    assert body["counts"]["total"] == len(states)
    assert body["counts"]["done"] + body["counts"]["upcoming"] == body["counts"]["total"]


def test_suggested_next_is_startable_not_merely_weakest(client: TestClient) -> None:
    """The weakest skill overall is usually locked three prerequisites deep. Sending a
    student at it is the exact mistake the project is about."""
    client.post("/session", json={"name": "Aarav"})
    body = client.get("/student/aarav/plan").json()
    suggested = body["suggested_next"]
    if suggested is not None:
        item = next(s for s in body["skills"] if s["skill"] == suggested)
        assert item["state"] == "available"


def test_plan_for_an_unknown_student_is_404(client: TestClient) -> None:
    assert client.get("/student/ghost/plan").status_code == 404


def test_hints_are_available_without_submitting_anything(client: TestClient) -> None:
    """A student afraid that asking for help will cost them something will not ask."""
    client.post("/session", json={"name": "Aarav"})
    client.post("/session/aarav/start", json={"name": "Aarav", "target_skill": "recursion"})
    before = client.get("/student/aarav/progress").json()

    body = client.post(
        "/session/aarav/hints",
        json={"code": "def total(n):\n    return n + total(n - 1)"},
    ).json()
    assert body["hints"], "a hint button that produces nothing is worse than no button"
    assert len(body["hints"]) >= 2, "help must be able to get stronger"

    after = client.get("/student/aarav/progress").json()
    assert after["total_attempts"] == before["total_attempts"], "asking cost an attempt"
    assert after["skills"] == before["skills"], "asking moved mastery"


def test_hints_follow_the_draft(client: TestClient) -> None:
    """The ladder is chosen from what they have written, not only the skill name."""
    client.post("/session", json={"name": "Aarav"})
    client.post("/session/aarav/start", json={"name": "Aarav", "target_skill": "recursion"})

    recursive = client.post(
        "/session/aarav/hints",
        json={"code": "def total(n):\n    return n + total(n - 1)"},
    ).json()["hints"]
    printing = client.post(
        "/session/aarav/hints",
        json={"code": "def add(a, b):\n    print(a + b)"},
    ).json()["hints"]
    assert recursive != printing, "the same ladder was offered for different mistakes"


def test_startup_indexes_the_corpus_without_blocking_the_port(tmp_path, monkeypatch) -> None:
    """A deployed host starts from a checkout with no index, and empty retrieval is
    silent -- it returns nothing and every problem quietly loses its grounding.

    This asserts both halves of the fix: the corpus IS indexed on startup, and startup
    RETURNS before that finishes. The second half is not fussiness -- uvicorn does not
    open the port until the lifespan yields, so indexing inline made a healthy process
    look, to the host's port scan, exactly like one that never came up. That cost a
    deploy.
    """
    import app.api.main as api
    from app.rag.store import VectorStore

    monkeypatch.setattr(api, "REPO_ROOT", Path.cwd())
    monkeypatch.setenv("COGNIFLOW_CHROMA_PATH", str(tmp_path / "chroma"))
    get_settings.cache_clear()

    try:
        with TestClient(app) as client:
            # The port is open the moment the context manager returns, whatever the
            # indexing thread is still doing.
            assert client.get("/health").status_code == 200

            assert api.INDEX_READY.wait(timeout=180), "the index never resolved"
            assert api.INDEX_STATUS == "ready", api.INDEX_STATUS
            assert VectorStore().count() > 0, "startup left retrieval empty"
    finally:
        get_settings.cache_clear()


def test_a_failed_index_still_releases_whoever_is_waiting() -> None:
    """The gate must open on failure as surely as on success.

    An index that will never arrive is survivable. A request that waits forever for one
    is not, and this is the path where that would happen.
    """
    import app.api.main as api

    import app.rag.store as store_module

    def explode(*_a, **_k):
        raise RuntimeError("no disk")

    api.INDEX_READY.clear()
    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(store_module, "VectorStore", explode)
        api._index_corpus()
        assert api.INDEX_READY.is_set(), "a waiter would have hung here forever"
        assert api.INDEX_STATUS.startswith("failed"), api.INDEX_STATUS
    finally:
        monkey.undo()
        api.INDEX_STATUS = "ready"
        api.INDEX_READY.set()


@pytest.mark.parametrize(
    ("origin", "allowed"),
    [
        ("https://cogniflow-sohanmandal1611-7709s-projects.vercel.app", True),
        ("https://cogniflow-git-main-sohanmandal1611-7709s-projects.vercel.app", True),
        ("http://localhost:3000", True),
        ("https://evil-cogniflow.vercel.app", False),
        ("https://cogniflow.vercel.app.attacker.example", False),
    ],
)
def test_cors_admits_the_frontend_and_nothing_that_merely_resembles_it(
    client: TestClient, origin: str, allowed: bool
) -> None:
    """Preview hostnames change on every push, so the allowlist has to be a pattern --
    and a sloppy pattern that matches by substring would admit any host that contains
    the project name."""
    headers = client.get("/health", headers={"Origin": origin}).headers
    assert ("access-control-allow-origin" in headers) is allowed, origin

DIAGNOSTIC_ANSWERS = {
    "variables": "x = 7\nx = x + 3\nprint(x)",
    "conditionals": "x = 9\nif x > 5:\n    print('big')\nelse:\n    print('small')",
    "loops": "total = 0\nfor i in range(1, 5):\n    total = total + i\nprint(total)",
}


def _sit_the_diagnostic(client: TestClient, student: str = "priya") -> dict:
    """Answer three topics correctly, leave the rest blank, and take the plan.

    Deliberately a FINISHED diagnostic. An unfinished one still reads the seeded demo
    profile, whose numbers are all comfortably above both thresholds -- so a test that
    stops early passes whatever the plan does, which is how a vacuous test looks.
    """
    client.post("/session", json={"name": student.title()})
    for _ in range(12):
        question = client.get(f"/session/{student}/diagnostic").json()
        if question["complete"]:
            break
        client.post(
            f"/session/{student}/diagnostic",
            json={
                "skill": question["skill"],
                "code": DIAGNOSTIC_ANSWERS.get(question["skill"], ""),
            },
        )
    return client.get(f"/student/{student}/plan").json()


def test_one_right_answer_is_not_a_completed_topic(client: TestClient) -> None:
    """The plan must not claim more than the guard would act on.

    A single correct answer puts BKT at mastery 0.85 on confidence 0.22. The plan tested
    mastery alone and so told a student who had answered one question per topic that
    five of eight topics were "Completed" -- while `policy.decide`, reading the identical
    numbers, would refuse to ADVANCE any of them. One word, two meanings, and the student
    was shown the wrong one.
    """
    plan = _sit_the_diagnostic(client)
    skills = plan["skills"]

    thin = [
        s for s in skills
        if s["mastery"] >= MASTERY_THRESHOLD and not is_mastered(s["mastery"], s["confidence"])
    ]
    assert thin, "this test proves nothing unless the diagnostic produced thin evidence"
    assert all(s["state"] == "provisional" for s in thin), (
        "a topic answered well on one question is neither finished nor untouched: "
        f"{[(s['skill'], s['state']) for s in thin]}"
    )

    for skill in skills:
        if skill["state"] == "completed":
            assert is_mastered(skill["mastery"], skill["confidence"]), (
                f"{skill['skill']} is shown as completed but the guard would not advance "
                f"on it: mastery={skill['mastery']} confidence={skill['confidence']}"
            )

    assert plan["counts"]["done"] == sum(1 for s in skills if s["state"] == "completed")
    assert plan["counts"]["provisional"] == len(thin)


def test_a_high_scoring_skill_is_never_locked_behind_a_weak_prerequisite(
    client: TestClient,
) -> None:
    """Locking is about prerequisites; this student's own evidence outranks it.

    Splitting "completed" by confidence put a new branch in front of the "locked" check,
    and getting that order wrong would shut a student out of a topic they had just
    answered correctly, because something upstream was unproven. That is the tutor
    arguing with its own observation.
    """
    plan = _sit_the_diagnostic(client, "aarav")
    for skill in plan["skills"]:
        if skill["mastery"] >= MASTERY_THRESHOLD:
            assert skill["state"] != "locked", (
                f"{skill['skill']} scores {skill['mastery']} and was locked anyway"
            )


def test_the_plan_points_where_the_diagnostic_pointed(client: TestClient) -> None:
    """The two screens a student sees back to back must not disagree.

    The diagnostic ends with "Start here: X" and the plan then computes its own
    suggestion, independently, from the stored profile. Nothing in the code makes them
    agree -- they agree because both reduce to "the weakest thing that can be started
    now", and this pins that. Live, they had already come apart: a student was told to
    start at recursion and handed a plan suggesting nested_loops.
    """
    client.post("/session", json={"name": "Meera"})
    summary: dict = {}
    for _ in range(12):
        question = client.get("/session/meera/diagnostic").json()
        if question["complete"]:
            summary = question
            break
        client.post(
            "/session/meera/diagnostic",
            json={
                "skill": question["skill"],
                "code": DIAGNOSTIC_ANSWERS.get(question["skill"], ""),
            },
        )

    plan = client.get("/student/meera/plan").json()
    assert plan["suggested_next"] == summary["weakest_skill"], (
        f"diagnostic said start at {summary['weakest_skill']!r}, "
        f"plan suggests {plan['suggested_next']!r}"
    )


def test_the_plan_counts_add_up(client: TestClient) -> None:
    """Three numbers shown side by side must be readable as three buckets.

    Adding "provisional" without touching "upcoming" -- which meant "not completed" --
    put the middle bucket in two places at once: 0 done, 3 looking good, 8 upcoming, out
    of a total of 8. Nobody reads that as containment; they read it as a bug.
    """
    plan = _sit_the_diagnostic(client, "rhea")
    counts = plan["counts"]
    assert counts["done"] + counts["provisional"] + counts["upcoming"] == counts["total"]
    assert counts["total"] == len(plan["skills"])
