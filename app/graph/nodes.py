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
from typing import Any, Callable

from langgraph.types import interrupt

from app.graph.deps import GraphDeps
from app.graph.state import AgentState
from app.llm.provider import Role
from app.mastery import policy
from app.mastery.bkt import update_skill
from app.mastery.guard import validate
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
from app.mastery.misconceptions import detect
from app.tools.sandbox.classifier import classify_with_expectation
from app.tools.sandbox.runner import run_test_cases

logger = logging.getLogger(__name__)

Node = Callable[[AgentState], dict[str, Any]]

MASTERY_THRESHOLD = policy.MASTERY_THRESHOLD


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
        assessment = (
            AssessmentType.CODE_TRACE
            if mode == TeachingMode.CODE_TRACE
            else AssessmentType.CODING
        )
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


def _template_problem(state: AgentState) -> GeneratedProblem:
    """Deterministic fallback used when no model is reachable.

    Keeps a session alive during a provider outage instead of ending it. The event log
    records that generation was degraded, so nothing pretends the model succeeded.
    """
    skill = state["target_skill"] or "python"
    difficulty = state.get("difficulty_level", Difficulty.MEDIUM)
    mode = state.get("teaching_mode", TeachingMode.TEXTUAL)
    if mode == TeachingMode.CODE_TRACE:
        prompt = (
            f"Trace this {skill} example by hand and print the final result.\n\n"
            "def add(a, b):\n    return a + b\n\n"
            "def compute(x):\n    doubled = add(x, x)\n    return add(doubled, x)\n\n"
            "print(compute(4))"
        )
        expected = "12"
    else:
        prompt = (
            f"Write a Python function demonstrating {skill}. "
            "Print the result of calling it so the output can be checked."
        )
        expected = ""
    return GeneratedProblem(
        title=f"{skill} practice ({difficulty})",
        prompt=prompt,
        skill=skill,
        difficulty=difficulty,
        assessment_type=state.get("assessment_type", AssessmentType.CODING),
        expected_output=expected,
        test_cases=[{"name": "default", "stdin": "", "expected_output": expected}] if expected else [],
    )


def make_generate_problem(deps: GraphDeps) -> Node:
    """LLM call site 1: author a task grounded in retrieved material."""

    def generate_problem(state: AgentState) -> dict[str, Any]:
        skill = state["target_skill"]
        context = "\n\n---\n".join(state.get("retrieved_context", [])[:3])
        recent = state.get("recent_problem_hashes", [])

        messages = [
            {
                "role": "system",
                "content": (
                    "You author short Python exercises for one student. Ground the task "
                    "in the supplied curriculum material. Return only the schema fields."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Skill: {skill}\nDifficulty: {state.get('difficulty_level')}\n"
                    f"Teaching mode: {state.get('teaching_mode')}\n"
                    f"Curriculum material:\n{context or '(none available)'}\n\n"
                    "Write one exercise. If it is a coding task, give an expected_output "
                    "that a correct solution would print."
                ),
            },
        ]
        outcome = deps.llm(Role.GENERATE).call_structured(
            GeneratedProblem, messages, fallback=_template_problem(state)
        )
        problem = outcome.value
        assert isinstance(problem, GeneratedProblem)

        problem.grounding_sources = [
            f"{s['source']}#{s['section']}" for s in state.get("retrieved_sources", [])[:3]
        ]
        fp = problem.fingerprint()

        deps.events.emit(
            "generate_problem",
            EventType.GENERATED,
            {
                "title": problem.title,
                "skill": problem.skill,
                "difficulty": str(problem.difficulty),
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
                "repeat": fp in recent,
            },
            evidence=problem.grounding_sources,
        )
        return {
            "current_problem": problem.model_dump(mode="json"),
            "current_problem_id": fp,
            "recent_problem_hashes": [*recent, fp][-10:],
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
        note = found.student_note if found is not None else analysis.misconception
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
