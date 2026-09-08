"""Graph nodes.

Invariant: only `update_mastery` may change a mastery score, and it can only be reached
along the valid-evidence edge. Every other path -- LLM failure, sandbox failure,
retrieval failure -- routes to `recover`, which leaves the student model untouched.

Node inventory, and which ones actually call a model:

    load_student          deterministic
    diagnose              deterministic   (graph traversal + arithmetic)
    plan_action           deterministic
    retrieve              tool            (vector search)
    generate_problem      LLM             <- call site 1
    await_student         interrupt
    classify_submission   deterministic   (reads the problem's own assessment_type)
    execute_code          tool            (sandbox)
    grade                 deterministic for code, LLM for prose  <- call site 2
    analyze_misconception LLM             <- call site 3
    update_mastery        deterministic   (BKT + write-through)
    adapt                 LLM proposes, deterministic guard disposes
    recover               deterministic

Three model call sites. Everything else is arithmetic, and arithmetic is already correct
and free.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from langgraph.types import interrupt

from app.graph.deps import GraphDeps
from app.graph.state import AgentState
from app.llm.provider import Role
from app.mastery import policy
from app.mastery.bkt import resolve_misconceptions, update_skill
from app.mastery.guard import validate
from app.mastery.difficulty import ladder_summary, rung_for
from app.mastery.policy import PolicyContext
from app.mastery.skill_graph import SkillGraph
from app.models.enums import (
    AdaptationAction,
    AssessmentType,
    Difficulty,
    SessionStatus,
    StudentOutcome,
    SystemFault,
    TeachingMode,
    is_student_evidence,
)
from app.models.schemas import (
    AdaptationDecision,
    GeneratedProblem,
    GradeResult,
    MisconceptionAnalysis,
    SkillNode,
)
from app.services.events import EventType
from app.mastery.misconceptions import detect, student_note_for
from app.tools.sandbox.classifier import classify_with_expectation
from app.tools.sandbox.runner import run_test_cases

logger = logging.getLogger(__name__)

Node = Callable[[AgentState], dict[str, Any]]

MASTERY_THRESHOLD = policy.MASTERY_THRESHOLD
CONFIDENCE_THRESHOLD = policy.CONFIDENCE_THRESHOLD


# ---------------------------------------------------------------- helpers
def _graph_from_state(state: AgentState) -> SkillGraph:
    """Rebuild the live skill graph from the serialized state."""
    nodes = {k: SkillNode(**v) for k, v in state.get("skill_graph", {}).items()}
    return SkillGraph(nodes)


def _difficulty_for(mastery: float) -> Difficulty:
    if mastery < 0.4:
        return Difficulty.EASY
    if mastery < 0.75:
        return Difficulty.MEDIUM
    return Difficulty.HARD


# ---------------------------------------------------------------- nodes
# How the student is taught decides how they are asked to show it. Deterministic on
# purpose: the shape of an assessment is a pedagogical choice, and an LLM would add
# nondeterminism to a mapping that is a lookup.
#
# Every value here is graded by EXECUTION. Assessment types that would need a rubric
# grader for free text are deliberately absent rather than declared and unreachable --
# see the note on AssessmentType.
ASSESSMENT_FOR_MODE: dict[TeachingMode, AssessmentType] = {
    TeachingMode.CODE_TRACE: AssessmentType.CODE_TRACE,
    # Shown a worked example, then handed a broken one: fixing it is the proof that the
    # example landed, and it is a harder test of the same understanding than writing
    # fresh code, where a student can route around what they do not know.
    TeachingMode.WORKED_EXAMPLE: AssessmentType.DEBUGGING,
    TeachingMode.ANALOGY: AssessmentType.CODING,
    TeachingMode.VISUAL_DESCRIPTION: AssessmentType.CODE_TRACE,
    TeachingMode.SOCRATIC_HINTS: AssessmentType.CODING,
    TeachingMode.TEXTUAL: AssessmentType.CODING,
}


def _error_summary(stderr: str) -> str:
    """The exception line from a traceback, without the frames above it.

    Python puts the useful sentence last, after the call stack. The stack is ours as
    much as theirs -- it names the sandbox harness -- so showing it makes a student
    scroll past our implementation to reach their own mistake.
    """
    lines = [ln.strip() for ln in (stderr or "").splitlines() if ln.strip()]
    if not lines:
        return ""
    for line in reversed(lines):
        if not line.startswith(("File ", "Traceback")):
            return line[:300]
    return lines[-1][:300]


def _latest_hint(state: AgentState, skill: str) -> str | None:
    """The most recently implicated prerequisite for this skill, if any.

    Only the current skill's diagnoses count: a misconception recorded while practising
    something else says nothing about why THIS skill is failing.
    """
    for entry in reversed(state.get("detected_misconceptions", [])):
        if entry.get("skill") == skill and entry.get("implicates"):
            return str(entry["implicates"])
    return None


def make_load_student(deps: GraphDeps) -> Node:
    """Hydrate durable mastery into session state."""

    def load_student(state: AgentState) -> dict[str, Any]:
        student_id = state["student_id"]
        deps.store.ensure_student(student_id, state.get("domain", "python_fundamentals"))
        skills = deps.store.load_skills(student_id)

        if not skills:
            skills = SkillGraph.from_yaml(deps.skills_config).nodes
            deps.store.save_skills(student_id, skills)

        deps.events.emit(
            "load_student",
            EventType.SESSION_START,
            {"student_id": student_id, "session_id": state["session_id"], "skills": len(skills)},
        )
        return {
            "skill_graph": {k: v.model_dump(mode="json") for k, v in skills.items()},
            "mastery_scores": {k: v.mastery for k, v in skills.items()},
            "confidence_scores": {k: v.confidence for k, v in skills.items()},
        }

    return load_student


def make_diagnose(deps: GraphDeps) -> Node:
    """Deterministic diagnosis: weakest skills and prerequisite gaps.

    No LLM here on purpose. Reading mastery scores off a graph is arithmetic, and an
    LLM would add latency, cost, and nondeterminism to a computation that is already
    exactly right.
    """

    def diagnose(state: AgentState) -> dict[str, Any]:
        graph = _graph_from_state(state)
        target = state.get("target_skill") or min(
            graph.nodes, key=lambda s: graph.nodes[s].mastery
        )
        unmastered = graph.unmastered_prerequisites(target, MASTERY_THRESHOLD)
        weak = sorted(
            (s for s, n in graph.nodes.items() if n.mastery < MASTERY_THRESHOLD),
            key=lambda s: graph.nodes[s].mastery,
        )
        node = graph.nodes[target]
        record = {
            "target_skill": target,
            "mastery": node.mastery,
            "weak_skills": weak[:5],
            "missing_prerequisites": unmastered,
        }
        deps.events.emit(
            "diagnose",
            EventType.DIAGNOSTIC,
            record,
            evidence=[f"{s}={graph.nodes[s].mastery:.2f}" for s in weak[:3]],
            confidence=node.confidence,
        )
        return {
            "target_skill": target,
            "current_skill": target,
            "diagnostic_history": [*state.get("diagnostic_history", []), record],
        }

    return diagnose


def make_plan_action(deps: GraphDeps) -> Node:
    """Choose skill, difficulty, assessment type, teaching mode."""

    def plan_action(state: AgentState) -> dict[str, Any]:
        graph = _graph_from_state(state)
        target = state["target_skill"] or state["current_skill"]
        assert target is not None
        mastery = graph.nodes[target].mastery
        difficulty = _difficulty_for(mastery)
        mode = state.get("teaching_mode") or TeachingMode.TEXTUAL
        assessment = ASSESSMENT_FOR_MODE.get(mode, AssessmentType.CODING)
        deps.events.emit(
            "plan_action",
            EventType.PLAN,
            {
                "target_skill": target,
                "difficulty": str(difficulty),
                "teaching_mode": str(mode),
                "assessment_type": str(assessment),
                "mastery": mastery,
            },
        )
        return {
            "target_skill": target,
            "difficulty_level": str(difficulty),
            "assessment_type": str(assessment),
            "teaching_mode": str(mode),
            "loop_count": state.get("loop_count", 0) + 1,
        }

    return plan_action


def make_retrieve(deps: GraphDeps) -> Node:
    """Ground the next task in real curriculum material."""

    def retrieve(state: AgentState) -> dict[str, Any]:
        skill = state["target_skill"]
        if deps.retriever is None:
            deps.events.emit("retrieve", EventType.RETRIEVAL, {"skipped": "no retriever"})
            return {"retrieved_context": [], "retrieved_sources": []}

        query = f"{skill} {state.get('teaching_mode', '')} explanation and worked example"
        evidence = deps.retriever.retrieve(query, skill=skill)
        deps.events.emit(
            "retrieve",
            EventType.RETRIEVAL,
            {
                "skill": skill,
                "chunks": len(evidence.chunks),
                "fallback": evidence.used_fallback,
                "degraded": evidence.degraded,
            },
            evidence=evidence.citations()[:3],
        )
        return {
            "retrieved_context": [c.text for c in evidence.chunks],
            "retrieved_sources": [
                {"source": c.source_file, "section": c.section, "skill": c.skill}
                for c in evidence.chunks
            ],
        }

    return retrieve


def _template_problem(state: AgentState, attempt: int = 0) -> GeneratedProblem:
    """Deterministic fallback used when no model is reachable.

    Keeps a session alive during a provider outage instead of ending it. The event log
    records that generation was degraded, so nothing pretends the model succeeded.

    It used to ignore difficulty completely: one sentence -- "Write a Python function
    demonstrating {skill}" -- served at every level, with only the title changing. A
    student who worked up from EASY to HARD got the same task three times. It now reads
    the ladder, so each level is a genuinely different exercise, and rotates through that
    rung's variants by `attempt` so a repeat visit is not a repeat question.

    Being honest about what this is: with no model reachable it cannot write new prose.
    It can stop lying about difficulty and stop repeating itself, and that is what it now
    does. Novel problems come from the live path.
    """
    skill = state["target_skill"] or "python"
    difficulty = state.get("difficulty_level", Difficulty.MEDIUM)
    mode = state.get("teaching_mode", TeachingMode.TEXTUAL)
    assessment = state.get("assessment_type", AssessmentType.CODING)
    rung = rung_for(skill, difficulty)

    starter = ""
    if assessment == AssessmentType.DEBUGGING:
        # The classic return-vs-print confusion, which is what a recursion failure
        # usually turns out to be. They must fix it and make it print 6.
        prompt = (
            "This program is meant to print 6, but it fails. Find the bug, fix it, and "
            "submit the corrected program."
        )
        starter = (
            "def add(a, b):\n"
            "    print(a + b)\n"
            "\n"
            "total = add(2, 3)\n"
            "print(total + 1)"
        )
        expected = "6"
    elif mode == TeachingMode.CODE_TRACE:
        prompt = (
            f"Trace this {skill} example by hand and print the final result.\n\n"
            "def add(a, b):\n    return a + b\n\n"
            "def compute(x):\n    doubled = add(x, x)\n    return add(doubled, x)\n\n"
            "print(compute(4))"
        )
        expected = "12"
    elif rung.variants:
        task = rung.variants[attempt % len(rung.variants)]
        prompt = task.prompt
        expected = task.expected
        starter = task.starter
    else:
        # A skill with no authored tasks still gets a level-appropriate demand rather
        # than the old one-size sentence.
        prompt = (
            f"Write a Python program about {skill} that requires {rung.demands}. "
            "Print the result so the output can be checked."
        )
        expected = ""

    return GeneratedProblem(
        title=f"{skill} practice ({difficulty})",
        prompt=prompt,
        skill=skill,
        difficulty=difficulty,
        assessment_type=assessment,
        starter_code=starter,
        expected_output=expected,
        test_cases=[{"name": "default", "stdin": "", "expected_output": expected}] if expected else [],
        concepts=list(rung.concepts),
        cognitive_level=rung.cognitive_level,
        complexity=rung.complexity,
        generation_seed=f"template:{skill}:{difficulty}:{attempt}",
    )


def _assessment_instruction(assessment: str | AssessmentType) -> str:
    """What this assessment shape requires of the generated problem.

    Kept out of the base prompt because each shape has a different, specific contract
    with the grader, and a generic instruction produces a task the grader cannot score.
    DEBUGGING in particular is worthless without starter_code: with no broken program to
    fix, the student is just being asked to write one from scratch.
    """
    if str(assessment) == AssessmentType.DEBUGGING:
        return (
            "This is a DEBUGGING task. Put a SHORT, genuinely broken program in "
            "starter_code -- one clear bug, of a kind that reveals a misunderstanding "
            "rather than a typo. The prompt must say what the program is supposed to "
            "print. expected_output must be what the FIXED program prints. Do not "
            "reveal the bug or the fix in the prompt."
        )
    if str(assessment) == AssessmentType.CODE_TRACE:
        return (
            "This is a CODE_TRACE task. Put the program to trace in the prompt, and set "
            "expected_output to what it prints. The student works it out by hand, so it "
            "must be short enough to follow without running it."
        )
    return (
        "This is a CODING task. The student writes the program from scratch, so "
        "starter_code should be empty."
    )


def make_generate_problem(deps: GraphDeps) -> Node:
    """LLM call site 1: author a task grounded in retrieved material."""

    def generate_problem(state: AgentState) -> dict[str, Any]:
        skill = state["target_skill"]
        difficulty = state.get("difficulty_level", Difficulty.MEDIUM)
        context = "\n\n---\n\n".join(state.get("retrieved_context", [])[:3])
        recent = state.get("recent_problem_hashes", [])
        seen_keys = state.get("recent_content_keys", [])
        rung = rung_for(skill, difficulty)

        def _ask(avoid: list[str], attempt: int) -> Any:
            """One generation attempt. `avoid` names prompts the student has already had."""
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You author short Python exercises for one student. Ground the "
                        "task in the supplied curriculum material. Return only the schema "
                        "fields."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Skill: {skill}\nDifficulty: {difficulty}\n"
                        f"Teaching mode: {state.get('teaching_mode')}\n"
                        f"Assessment type: {state.get('assessment_type')}\n\n"
                        # The whole ladder, not just the rung being asked for. "Make this
                        # HARD" is meaningless without knowing what EASY already covered:
                        # difficulty is a relation between levels, not a property of one.
                        f"What each level means for this skill:\n{ladder_summary(skill)}\n\n"
                        f"You are writing the {difficulty} one. It must demand "
                        f"{rung.demands}. Concepts in play: {', '.join(rung.concepts)}. "
                        f"Cognitive level: {rung.cognitive_level}.\n\n"
                        "A harder level is NOT the same task with bigger numbers, a longer "
                        "list, or renamed variables. It is a DIFFERENT problem requiring "
                        "deeper reasoning."
                        + (
                            f"\n\nThis student has already been given the following. Do "
                            f"not repeat them or write a variation of them:\n- "
                            + f"\n- ".join(avoid)
                            if avoid
                            else ""
                        )
                        + f"\n\nCurriculum material:\n{context or '(none available)'}\n\n"
                        "Write one exercise. If it is a coding task, give an "
                        "expected_output that a correct solution would print."
                        + _assessment_instruction(
                            state.get("assessment_type", AssessmentType.CODING)
                        )
                    ),
                },
            ]
            return deps.llm(Role.GENERATE).call_structured(
                GeneratedProblem, messages, fallback=_template_problem(state, attempt)
            )

        # Generate, and if the result is something this student has already seen, say so
        # and ask again. The old code computed `fp in recent`, put it in the event log as
        # "repeat": true, and served the problem anyway -- the check existed and nothing
        # acted on it. Two retries, because a model that has ignored the avoid-list twice
        # will ignore it a third time, and a student waiting on a fourth round trip is a
        # worse outcome than a familiar question.
        recent_prompts = state.get("recent_prompts", [])
        attempts = 0
        for attempts in range(3):
            outcome = _ask(recent_prompts[-4:], attempts)
            problem = outcome.value
            assert isinstance(problem, GeneratedProblem)
            if problem.content_key() not in seen_keys:
                break

        problem.grounding_sources = [
            f"{s['source']}#{s['section']}" for s in state.get("retrieved_sources", [])[:3]
        ]
        # Metadata from the rung rather than from the model. A model asked to
        # self-report its own difficulty will agree with whatever it was told; the
        # ladder is the authority on what this level demands.
        problem.concepts = list(rung.concepts)
        problem.cognitive_level = rung.cognitive_level
        problem.complexity = rung.complexity

        # Server-assigned, unconditionally, because the model will happily supply its
        # own. Observed live: it returned problem_id="loop_sum_easy_001" -- readable,
        # plausible, and guaranteed to collide the next time any student anywhere is
        # given an easy loop-sum task. An identifier a generator invents from the
        # content is not an identifier, it is a slug. The requirement is uniqueness,
        # and only the server can promise that.
        problem.problem_id = uuid4().hex[:12]
        problem.generation_seed = f"live:{skill}:{difficulty}:{attempts}"

        fp = problem.fingerprint()
        key = problem.content_key()
        repeated = key in seen_keys

        deps.events.emit(
            "generate_problem",
            EventType.GENERATED,
            {
                "title": problem.title,
                "skill": problem.skill,
                "difficulty": str(problem.difficulty),
                "concepts": ",".join(problem.concepts),
                "cognitive_level": problem.cognitive_level,
                "problem_id": problem.problem_id,
                "degraded": outcome.used_fallback,
                "provider": outcome.provider_used,
                # Why it degraded, not just that it did. A key that is present but
                # rejected and a key that was never set both read as degraded=True,
                # and on a deployment whose logs we cannot open that is the whole
                # difference. None when the call succeeded, so it renders only when
                # it has something to say.
                "fault": str(outcome.fault) if outcome.used_fallback else None,
                "tried": ",".join(outcome.providers_tried) if outcome.used_fallback else None,
                # Truncated: enough to tell a rejected key from a rate limit from a
                # network failure, which are three different fixes and are otherwise
                # one indistinguishable degraded=True. Provider error strings carry
                # status and reason, never the credential.
                "why": (outcome.error_message or "")[:90] if outcome.used_fallback else None,
                # Reported after the retries, so a true here means we asked again and
                # still could not get something new -- not merely that the first draft
                # was familiar.
                "repeat": repeated,
                "regenerations": attempts,
            },
            evidence=problem.grounding_sources,
            reason=(
                f"{difficulty} {skill}: {rung.demands}"
                + (" (repeat -- could not produce a new one)" if repeated else "")
            ),
        )
        return {
            "current_problem": problem.model_dump(mode="json"),
            "current_problem_id": problem.problem_id,
            "recent_problem_hashes": [*recent, fp][-10:],
            "recent_content_keys": [*seen_keys, key][-20:],
            "recent_prompts": [*recent_prompts, problem.prompt][-6:],
        }

    return generate_problem


def make_await_student(deps: GraphDeps) -> Node:
    """The genuine suspension point.

    `interrupt` checkpoints the entire state and halts. A different process, minutes
    later, resumes this same thread from that checkpoint. That is what separates a real
    human-in-the-loop graph from a loop that merely waits.
    """

    def await_student(state: AgentState) -> dict[str, Any]:
        problem = state.get("current_problem") or {}
        deps.events.emit(
            "await_student",
            EventType.AWAITING_STUDENT,
            {"problem_id": state.get("current_problem_id"), "title": problem.get("title")},
        )
        submission = interrupt(
            {
                "problem": problem,
                "skill": state.get("target_skill"),
                "attempt": state.get("attempt_count", 0) + 1,
            }
        )
        if isinstance(submission, dict):
            code = submission.get("code")
            answer = submission.get("answer")
        else:
            code, answer = str(submission), None

        deps.events.emit(
            "await_student",
            EventType.SUBMISSION,
            {"has_code": bool(code), "chars": len(code or answer or "")},
        )
        return {
            "student_code": code,
            "student_answer": answer,
            "attempt_count": state.get("attempt_count", 0) + 1,
        }

    return await_student


def make_execute_and_grade(deps: GraphDeps) -> Node:
    """Run the submission and grade it.

    Code is graded by EXECUTION, not by asking a model whether it looks right.
    """

    def execute_and_grade(state: AgentState) -> dict[str, Any]:
        problem = state.get("current_problem") or {}
        code = state.get("student_code")

        if not code:
            grade = GradeResult(passed=False, score=0.0, feedback="No submission received.")
            return {
                "grader_result": grade.model_dump(mode="json"),
                "execution_result": None,
                "error_type": StudentOutcome.WRONG_ANSWER.value,
            }

        raw_cases = problem.get("test_cases") or []
        expected = (problem.get("expected_output") or "").strip()

        # Keep only cases that can actually decide pass/fail. A model will happily emit
        # test_cases carrying stdin but no expectation, alongside a usable top-level
        # expected_output -- and an unusable case must not shadow a usable field, or
        # every submission fails against an empty string.
        cases = [
            case
            for case in raw_cases
            if isinstance(case, dict)
            and str(
                case.get("expected_output")
                or case.get("expected")
                or case.get("output")
                or ""
            ).strip()
        ]
        if not cases and expected:
            cases = [{"name": "default", "stdin": "", "expected_output": expected}]

        if cases:
            suite = run_test_cases(deps.sandbox, code, cases)
            first = suite.first_failure
            exec_result = (
                first.execution if first else suite.results[-1].execution
                if suite.results
                else None
            )
            passed = suite.all_passed
            score = suite.passed_count / max(suite.total_count, 1)
            failing = first.name if first else None
        else:
            exec_result = deps.sandbox.run(code)
            passed = exec_result.status.value == "ok"
            score = 1.0 if passed else 0.0
            failing = None
            suite = None

        if exec_result is None:
            outcome: StudentOutcome | SystemFault = StudentOutcome.WRONG_ANSWER
        else:
            outcome = classify_with_expectation(exec_result, passed)

        grade = GradeResult(
            passed=bool(passed and is_student_evidence(outcome) and outcome == StudentOutcome.CORRECT),
            score=float(score),
            # The exception's own last line, not the whole traceback. A student reading
            # "NameError: name 'tota' is not defined" learns something; the same message
            # buried under six frames of our sandbox harness does not. Replaced outright
            # by analyze_misconception when a rule recognises the underlying cause.
            feedback=_error_summary(exec_result.stderr if exec_result else ""),
            failing_case=failing,
        )

        deps.events.emit(
            "execute_and_grade",
            EventType.EXECUTION,
            {
                "status": exec_result.status.value if exec_result else "none",
                "started": exec_result.started if exec_result else False,
                "outcome": str(outcome),
                "passed": grade.passed,
                "score": grade.score,
            },
        )
        return {
            "execution_result": exec_result.model_dump(mode="json") if exec_result else None,
            "grader_result": grade.model_dump(mode="json"),
            "error_type": str(outcome),
        }

    return execute_and_grade


def make_analyze_misconception(deps: GraphDeps) -> Node:
    """LLM call site 3: name what the student actually misunderstands.

    Reached only on the student-evidence path, and only after a failure -- there is
    nothing to diagnose about a correct answer.

    Deterministic patterns run FIRST. A RecursionError means a missing base case; that
    is what the exception means, not a matter of opinion, and asking a model to infer it
    would add cost and nondeterminism to a settled question. The model is consulted only
    when the rules cannot name the failure.

    This node is deliberately non-fatal. A misconception is useful colour, not evidence:
    if analysis fails entirely the session continues and mastery still updates, because
    the student's submission was real regardless of whether we could explain it.
    """

    def analyze_misconception(state: AgentState) -> dict[str, Any]:
        raw = state.get("error_type") or ""
        try:
            outcome = StudentOutcome(raw)
        except ValueError:
            return {}
        if outcome == StudentOutcome.CORRECT:
            return {}

        skill = state["target_skill"]
        assert skill is not None
        execution = state.get("execution_result") or {}
        code = state.get("student_code") or ""

        found = detect(
            code=code,
            stdout=str(execution.get("stdout", "")),
            stderr=str(execution.get("stderr", "")),
            outcome=outcome,
        )

        if found is not None:
            analysis = MisconceptionAnalysis(
                misconception=found.label,
                evidence=[f"pattern:{found.key}", f"outcome:{outcome.value}"],
                likely_prerequisite_gap=found.prerequisite_hint,
                confidence=0.9,
            )
            source = "deterministic"
        else:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You name the single specific misunderstanding behind a failed "
                        "programming submission. Be concrete about what the student "
                        "believes that is untrue. Do not restate the error message."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Skill being practised: {skill}\n"
                        f"Outcome: {outcome.value}\n"
                        f"Their code:\n{code[:1200]}\n\n"
                        f"stderr:\n{str(execution.get('stderr', ''))[:600]}\n"
                        f"stdout:\n{str(execution.get('stdout', ''))[:300]}"
                    ),
                },
            ]
            result = deps.llm(Role.ANALYZE).call_structured(
                MisconceptionAnalysis,
                messages,
                fallback=MisconceptionAnalysis(
                    misconception=f"unresolved difficulty with {skill}",
                    evidence=[f"outcome:{outcome.value}"],
                    confidence=0.2,
                ),
            )
            analysis = result.value  # type: ignore[assignment]
            assert isinstance(analysis, MisconceptionAnalysis)
            source = result.provider_used or "fallback"

        # Record it on the skill itself, so it persists across sessions and can inform
        # future problem generation. Deduplicated: repeating the same misconception is
        # signal about frequency, not new information.
        skills = dict(state.get("skill_graph", {}))
        node_data = dict(skills.get(skill, {}))
        existing = list(node_data.get("misconceptions", []))
        if analysis.misconception not in existing:
            existing.append(analysis.misconception)
            node_data["misconceptions"] = existing[-5:]
            skills[skill] = node_data
            try:
                deps.store.save_skill(state["student_id"], SkillNode(**node_data))
            except Exception as exc:  # noqa: BLE001 - colour must not break a session
                logger.warning("could not persist misconception: %s", exc)

        deps.events.emit(
            "analyze_misconception",
            EventType.MISCONCEPTION,
            {
                "skill": skill,
                "misconception": analysis.misconception,
                "implicates": analysis.likely_prerequisite_gap,
                "source": source,
            },
            evidence=analysis.evidence,
            confidence=analysis.confidence,
        )

        # Give the student the diagnosis we just made. Until now `feedback` carried the
        # raw stderr, which tells someone who already understands the error exactly what
        # they already knew, and tells everyone else nothing. This node is the first
        # point where the CAUSE is known, so it is the right place to phrase it.
        patch: dict[str, Any] = {
            "skill_graph": skills,
            "detected_misconceptions": [
                *state.get("detected_misconceptions", []),
                {
                    "skill": skill,
                    "misconception": analysis.misconception,
                    "implicates": analysis.likely_prerequisite_gap,
                    "confidence": analysis.confidence,
                },
            ],
        }
        # The wording follows the code they actually wrote, not the pattern's name.
        note = (
            student_note_for(found, code) if found is not None else analysis.misconception
        )
        if note:
            grade = dict(state.get("grader_result") or {})
            grade["feedback"] = note
            patch["grader_result"] = grade
        return patch

    return analyze_misconception


def make_update_mastery(deps: GraphDeps) -> Node:
    """The ONLY node that changes a mastery score.

    Reachable exclusively along the valid-evidence edge. If a SystemFault ever arrives
    here the BKT layer raises rather than silently penalising the student.
    """

    def update_mastery(state: AgentState) -> dict[str, Any]:
        raw = state.get("error_type") or ""
        outcome = StudentOutcome(raw)
        skill = state["target_skill"]
        assert skill is not None

        graph = _graph_from_state(state)
        node = graph.nodes[skill]
        updated, audit = update_skill(node, outcome, deps.bkt)

        # Resolution belongs here because this is the only place mastery moves, so it is
        # the only place the bar for "they have grown out of it" can newly be met.
        updated, resolved = resolve_misconceptions(
            updated, MASTERY_THRESHOLD, CONFIDENCE_THRESHOLD
        )
        if resolved:
            deps.events.emit(
                "update_mastery",
                EventType.MISCONCEPTION,
                {"skill": skill, "resolved": len(resolved)},
                reason=(
                    f"{skill} reached mastery with confidence; "
                    f"{len(resolved)} misconception(s) marked resolved"
                ),
                evidence=resolved[:3],
            )

        deps.store.save_skill(state["student_id"], updated)
        deps.store.log_attempt(state["student_id"], state["session_id"], audit)

        skills = dict(state.get("skill_graph", {}))
        skills[skill] = updated.model_dump(mode="json")
        mastery = dict(state.get("mastery_scores", {}))
        mastery[skill] = updated.mastery
        confidence = dict(state.get("confidence_scores", {}))
        confidence[skill] = updated.confidence

        passed = outcome == StudentOutcome.CORRECT
        failures = 0 if passed else state.get("consecutive_failures", 0) + 1
        topic = dict(state.get("topic_attempt_count", {}))
        topic[skill] = topic.get(skill, 0) + 1

        deps.events.emit(
            "update_mastery",
            EventType.MASTERY,
            {
                "skill": skill,
                "outcome": str(outcome),
                "before": round(audit.mastery_before, 4),
                "after": round(audit.mastery_after, 4),
                "attempts": audit.attempts_after,
            },
        )
        return {
            "skill_graph": skills,
            "mastery_scores": mastery,
            "confidence_scores": confidence,
            "consecutive_failures": failures,
            "topic_attempt_count": topic,
            "assessment_history": [
                *state.get("assessment_history", []),
                {"skill": skill, "outcome": str(outcome), "mastery": audit.mastery_after},
            ],
        }

    return update_mastery


def make_adapt(deps: GraphDeps) -> Node:
    """The architectural spine: the model proposes, the guard disposes."""

    def adapt(state: AgentState) -> dict[str, Any]:
        graph = _graph_from_state(state)
        skill = state["target_skill"]
        assert skill is not None
        raw = state.get("error_type") or ""
        try:
            outcome: StudentOutcome | None = StudentOutcome(raw)
        except ValueError:
            outcome = None

        ctx = PolicyContext(
            target_skill=skill,
            graph=graph,
            last_outcome=outcome,
            consecutive_failures=state.get("consecutive_failures", 0),
            topic_attempts=state.get("topic_attempt_count", {}).get(skill, 0),
            loop_count=state.get("loop_count", 0),
            prereq_depth=state.get("prereq_depth", 0),
            prereq_return_stack=list(state.get("prereq_return_stack", [])),
            current_difficulty=Difficulty(state.get("difficulty_level", Difficulty.MEDIUM)),
            teaching_mode=TeachingMode(state.get("teaching_mode", TeachingMode.TEXTUAL)),
            misconception_hint=_latest_hint(state, skill),
        )

        rule_based = policy.decide(ctx)
        messages = [
            {
                "role": "system",
                "content": (
                    "You choose the next tutoring action. A deterministic guard will "
                    "validate your choice and override it if it violates the rules."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Skill: {skill}\nMastery: {graph.nodes[skill].mastery:.2f}\n"
                    f"Consecutive failures: {ctx.consecutive_failures}\n"
                    f"Unmastered prerequisites: {graph.unmastered_prerequisites(skill)}\n"
                    "Choose one action and explain briefly."
                ),
            },
        ]
        proposal = deps.llm(Role.ADAPT).call_structured(
            AdaptationDecision, messages, fallback=rule_based
        )
        proposed = proposal.value
        assert isinstance(proposed, AdaptationDecision)

        verdict = validate(proposed, ctx)
        final = verdict.final

        if verdict.overridden:
            deps.events.emit(
                "adapt",
                EventType.GUARD_OVERRIDE,
                {
                    "proposed": str(verdict.proposed_action),
                    "final": str(final.action),
                    "violated": verdict.violated_rules,
                },
                reason="guard rejected the proposal",
            )

        deps.events.emit(
            "adapt",
            EventType.ADAPTATION,
            {
                "action": str(final.action),
                "target_skill": final.target_skill or skill,
                "overridden": verdict.overridden,
            },
            reason=final.reason,
            evidence=final.evidence,
            confidence=final.confidence,
        )

        patch: dict[str, Any] = {
            "next_action": str(final.action),
            "last_action": str(final.action),
            "decision_reason": final.reason,
            "decision_evidence": final.evidence,
            "decision_confidence": final.confidence,
            "guard_override": verdict.overridden,
        }

        if final.action == AdaptationAction.REVISIT_PREREQUISITE and final.target_skill:
            stack = list(state.get("prereq_return_stack", []))
            if stack and final.target_skill == stack[-1]:
                stack.pop()
                patch["prereq_depth"] = max(0, state.get("prereq_depth", 0) - 1)
                deps.events.emit(
                    "adapt",
                    EventType.PREREQ_RETURN,
                    {"returning_to": final.target_skill},
                    reason="prerequisite mastered; resuming the original objective",
                )
            else:
                stack.append(skill)
                patch["prereq_depth"] = state.get("prereq_depth", 0) + 1
                deps.events.emit(
                    "adapt",
                    EventType.PREREQ_REDIRECT,
                    {"from_skill": skill, "to_skill": final.target_skill},
                    reason=final.reason,
                )
            patch["prereq_return_stack"] = stack
            patch["target_skill"] = final.target_skill
            patch["consecutive_failures"] = 0
            patch["teaching_mode"] = str(final.teaching_mode or TeachingMode.CODE_TRACE)

        elif final.action in (AdaptationAction.ADVANCE, AdaptationAction.ESCALATE_DIFFICULTY):
            patch["consecutive_failures"] = 0
        elif final.action == AdaptationAction.EXPLAIN_DIFFERENTLY:
            patch["teaching_mode"] = str(final.teaching_mode or TeachingMode.WORKED_EXAMPLE)

        return patch

    return adapt


def make_recover(deps: GraphDeps) -> Node:
    """Handle a SystemFault without touching the student model."""

    def recover(state: AgentState) -> dict[str, Any]:
        fault = state.get("error_type") or SystemFault.SYSTEM_ERROR.value
        errors = state.get("error_count", 0) + 1
        deps.events.emit(
            "recover",
            EventType.RECOVERY,
            {"fault": fault, "error_count": errors, "mastery_untouched": True},
            reason="infrastructure fault; student model deliberately left unchanged",
        )
        patch: dict[str, Any] = {
            "error_count": errors,
            "last_error": fault,
            "next_action": str(AdaptationAction.RETRY_VARIATION),
        }
        if errors > 5:
            patch["session_status"] = str(SessionStatus.HALTED_ERROR)
            patch["next_action"] = str(AdaptationAction.COMPLETE)
        return patch

    return recover


def make_finalize(deps: GraphDeps) -> Node:
    """Close the session out."""

    def finalize(state: AgentState) -> dict[str, Any]:
        status = state.get("session_status", SessionStatus.ACTIVE)
        if status == SessionStatus.ACTIVE:
            status = (
                SessionStatus.HALTED_LIMIT
                if state.get("loop_count", 0) >= deps.max_loops
                else SessionStatus.COMPLETED
            )

        # A session that ends without saying what comes next leaves the student exactly
        # where an untutored one would be: finished, and guessing. The graph already
        # knows -- mastering a skill unlocks whatever depended on it.
        recommended: str | None = None
        reason: str | None = None
        target = state.get("target_skill")
        if target:
            graph = _graph_from_state(state)
            if graph.is_mastered(target, MASTERY_THRESHOLD):
                unlocked = graph.next_skills(target, MASTERY_THRESHOLD)
                if unlocked:
                    recommended = unlocked[0]
                    reason = (
                        f"{target} is mastered, and it was the last prerequisite "
                        f"{recommended} was waiting on"
                    )

        payload: dict[str, Any] = {
            "status": str(status),
            "loops": state.get("loop_count", 0),
            "skills_touched": sorted(state.get("topic_attempt_count", {})),
        }
        if recommended:
            payload["recommended_next"] = recommended
        deps.events.emit("finalize", EventType.SESSION_END, payload, reason=reason)

        patch: dict[str, Any] = {"session_status": str(status)}
        if recommended:
            patch["recommended_next_skill"] = recommended
        return patch

    return finalize
