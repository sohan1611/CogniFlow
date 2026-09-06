"""The HTTP API.

These assert the CONTRACT a frontend depends on, not the tutoring behaviour -- that is
covered by the graph tests, and duplicating it here would just make both harder to
change. What matters is that the fields a client draws from keep existing and keep
meaning what they mean.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.main import SESSIONS, app


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
