"""Which skill a failure is actually evidence against.

Until now every failed submission debited the skill the student was practising. That is
wrong in a specific, common and demoralising way: a student sent to a loops exercise who
writes `total` before defining it has made a scope mistake, and the tutor says so in its
feedback -- and then took the mark off loops.

The diagnosis already exists. app/mastery/misconceptions.py matches the interpreter's own
stderr and resolves a NameError to `prerequisite_hint="variables"`. That hint was already
good enough to choose the student's NEXT exercise; it simply never reached the arithmetic.
This module is the missing step.

Deliberately boring, because it decides what a student's record says about them:
deterministic, one hop, failures only, and the shares always partition exactly one
observation.
"""

from collections.abc import Iterable

# How much of a failure moves to the named prerequisite.
#
# 0.60 rather than 1.0: the rule fired on the interpreter's own output -- a NameError IS a
# scope fact, not an opinion -- so the prerequisite takes the larger share. But the student
# did also fail the loops task, and a tutor that concluded "this tells us nothing about
# loops" would quietly stop tracking the skill they came to learn.
ALPHA = 0.60


def debits(
    target: str,
    hint: str | None,
    prerequisites: Iterable[str],
    alpha: float = ALPHA,
) -> list[tuple[str, float]]:
    """Split one FAILED observation between the practised skill and an implicated prerequisite.

    Returns (skill, share) pairs whose shares sum to exactly 1.0, so one submission stays
    one observation no matter how it is divided -- double counting is impossible by
    construction rather than by review.

    Three rules, each of which exists to stop a specific failure mode:

    - Only a DIRECT prerequisite edge qualifies. A hint two hops up the DAG gets nothing.
      The edges are the only claims we are willing to make from a single mistake;
      walking further is how one typo quietly repaints a student's whole profile.
      Multi-hop remediation is the router's job (app/mastery/policy.py) and it already
      does it, on accumulated evidence rather than on one event.

    - Failures only. The caller must not use this for a correct answer: solving a loops
      problem is not evidence about variables, and crediting prerequisites would inflate
      skills the student never exercised.

    - No exemption for a well-established prerequisite. If variables sits at 0.95 a real
      NameError still dents it; p_slip is what absorbs the occasional slip of someone who
      does know. Protecting high scores from evidence is how a mastery estimate stops
      being a measurement.
    """

    if hint is None or hint == target or hint not in set(prerequisites):
        return [(target, 1.0)]
    return [(target, 1.0 - alpha), (hint, alpha)]
