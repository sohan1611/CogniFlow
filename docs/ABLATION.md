# Reducing the false-redirect rate

**Result: false redirects fell from 25% to 7.5%. Gap detection fell from 65% to 57.5%.**
Reproduce with `make ablation` — it is deterministic and costs nothing.

---

## The problem

The original three-arm study showed prerequisite-aware adaptation clearly beating the
no-prerequisite baseline, but with an honest cost:

```
arm                  mastered   med steps  gap found   false rdr   est err
A_no_prerequisite      100.0%          14       0.0%        0.0%     0.211
B_rules                100.0%          10      65.0%       25.0%     0.106
```

**A quarter of students whose prerequisites were genuinely fine were sent on a detour
they did not need.**

### Why

After two failures the policy redirected if *any* prerequisite looked unmastered. But
"unmastered" meant the **tutor's estimate** was below 0.6, and after a two-question
pre-test that estimate is barely better than the prior. The tutor was acting confidently
on a number it had no right to be confident about.

---

## What did not work, and why it is worth recording

The first attempt added a **relative margin** gate: redirect only if the prerequisite is
meaningfully weaker than the skill being practised.

**It reduced gap detection to 0%.** Arm B became identical to Arm A.

The gate was conceptually backwards, and the reason is instructive: *by the time a
redirect is under consideration, the student has already failed the target twice, so the
target's estimate has fallen below the prerequisite's.* `target − prerequisite` is
negative, so the gate could essentially never fire.

A second attempt used a stricter **absolute** threshold for acting. The trade-off proved
to be a cliff rather than a curve:

| action threshold | gap found | false rdr |
|---|---|---|
| 0.50 – 0.40 | 65.0% | 25.0% |
| 0.35 – 0.30 | 42.5% | 5.0% |

No setting satisfied both targets. With only two observations the posterior lands on a
handful of discrete values, so the threshold was choosing between clusters rather than
tuning a boundary.

---

## What actually worked: more evidence, not a better threshold

The populations separate cleanly once you look at what the pre-test does to a 0.35 prior:

| student | pre-test result | estimate |
|---|---|---|
| control | 2 correct | 0.942 |
| control | 1 wrong, 1 correct | 0.605 |
| **gapped** | 1 correct, 1 wrong | **0.383** |
| **gapped** | 2 wrong | **0.176** |

The false redirects were control students who got *unlucky* and drifted into the
0.45–0.60 band. The fix is not a cleverer boundary — it is **a third observation**.

| pre-test budget | gap found | false rdr | med steps |
|---|---|---|---|
| 2 | 65.0% | 25.0% | 10 |
| **3** | **57.5%** | **7.5%** | **13** |
| 4 | 55.0% | 12.5% | 14.5 |

**The evidence budget is derived, not chosen.** The policy refuses to redirect on a
prerequisite whose estimate has confidence below `PREREQ_EVIDENCE_CONFIDENCE = 0.5`, and
`confidence_from_attempts` only crosses 0.5 at the third observation. The diagnostic
pre-test asks three questions *because the policy requires that much evidence* — not the
other way round.

Note that four observations is **worse** than three on both axes. More evidence is not
monotonically better here: the extra step costs everyone time while the populations had
already separated.

---

## Final result

```
arm                  mastered   med steps  gap found   false rdr   est err
A_no_prerequisite      100.0%          16       0.0%        0.0%     0.205
B_rules                100.0%          13      57.5%        7.5%     0.130
C_guarded_model        100.0%          13      57.5%        7.5%     0.130
```

| | before | after |
|---|---|---|
| False redirect | 25.0% | **7.5%** (3.3× lower) |
| Gap detection | 65.0% | 57.5% |
| Median steps (B) | 10 | 13 |
| Advantage over baseline | 4 steps | 3 steps |

**The trade we accepted:** roughly one in eight fewer true gaps found, in exchange for
roughly one third as many students sent on pointless detours. We judged that worthwhile
because a false redirect is a visible, immediate cost to a student who was doing fine,
while a missed gap still leaves the ordinary adaptive machinery working on the target
skill. Reasonable people could weigh this differently, which is why both numbers are
reported rather than just the flattering one.

---

## An honest note on the threshold

`PREREQ_REDIRECT_THRESHOLD` is currently **non-binding**. At a three-observation budget
every value from 0.30 to 0.50 produces identical results, because the populations have
already separated. It is retained as a floor should the evidence budget ever be reduced,
and it is documented as inert rather than credited with an improvement it did not
produce.

The honest summary is: **the fix was gathering enough evidence, not tuning a gate.**

---

## The bypass that keeps the demo working

A **diagnosed misconception bypasses both gates.** If the student's code shows an
unreturned recursive call, we do not need three more data points to believe `functions`
is the problem — direct evidence of the mistake outranks any statistical bar.

This is what preserves the headline demo. There, `functions` sits at 0.55: weak, but not
badly enough broken to justify abandoning recursion on mastery alone. The redirect fires
because the misconception implicates it. Both `demo.py --verify` and
`demo.py --live --verify` still pass all seven self-checks.

The bypass cannot be abused. A hint may only promote a skill that is genuinely an
unmastered prerequisite of the current one, so a bad diagnosis can never send a student
somewhere arbitrary — asserted in `tests/test_policy_evidence.py`.

---

## Guard

`redirect_without_sufficient_evidence` applies the same gates to model proposals. A
model may suggest a detour the rules would not take; the guard stops it unless a
misconception backs it up.
