"""Fit BKT parameters from student trajectories, and check whether it was worth it.

Invariant: fitted parameters are ADOPTED only if they beat literature defaults on
HELD-OUT data. If they do not, we ship the defaults and report that plainly. A negative
result stated honestly is stronger than a tuned number nobody can reproduce.

ANTI-CIRCULARITY
Fitting on data you generated with the same model you are fitting is a fair criticism,
so the training data does NOT come from a BKT process. It comes from the simulator in
eval/simulator.py, whose generative story is different in kind: latent continuous skill,
multiplicative prerequisite gating, and a learning rate that collapses when
prerequisites are missing. BKT has no notion of any of that. So this measures whether
BKT's four parameters can be tuned to track a process that is genuinely not BKT --
which is the situation a real deployment is in.

METHOD
Direct likelihood maximisation over the four parameters by coarse grid search plus
local refinement. This is deliberately NOT called EM: it is a simpler procedure, and
naming it accurately matters more than naming it impressively. With four bounded
parameters and a few thousand sequences, grid search is adequate and fully
reproducible.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from itertools import product

from app.mastery.bkt import BKTParams

Sequence = list[bool]


# ---------------------------------------------------------------- likelihood
def sequence_log_likelihood(seq: Sequence, prm: BKTParams) -> float:
    """Log P(observations | parameters) under standard BKT."""
    import math

    p_known = prm.p_init
    total = 0.0
    for correct in seq:
        if correct:
            p_obs = p_known * (1 - prm.p_slip) + (1 - p_known) * prm.p_guess
        else:
            p_obs = p_known * prm.p_slip + (1 - p_known) * (1 - prm.p_guess)
        p_obs = min(max(p_obs, 1e-9), 1 - 1e-9)
        total += math.log(p_obs)

        # posterior, then the learning transition
        if correct:
            num = p_known * (1 - prm.p_slip)
        else:
            num = p_known * prm.p_slip
        p_known = num / p_obs
        p_known = p_known + (1 - p_known) * prm.p_transit
    return total


def predict_next(seq: Sequence, prm: BKTParams) -> float:
    """P(next answer correct) after observing `seq`. Used for held-out AUC."""
    p_known = prm.p_init
    for correct in seq:
        if correct:
            p_obs = p_known * (1 - prm.p_slip) + (1 - p_known) * prm.p_guess
            num = p_known * (1 - prm.p_slip)
        else:
            p_obs = p_known * prm.p_slip + (1 - p_known) * (1 - prm.p_guess)
            num = p_known * prm.p_slip
        p_obs = min(max(p_obs, 1e-9), 1 - 1e-9)
        p_known = num / p_obs
        p_known = p_known + (1 - p_known) * prm.p_transit
    return p_known * (1 - prm.p_slip) + (1 - p_known) * prm.p_guess


# ---------------------------------------------------------------------- AUC
def auc(scores: list[float], labels: list[bool]) -> float:
    """Rank-based ROC AUC, with ties handled by averaging ranks.

    Implemented here rather than pulled from scikit-learn: the project deliberately
    avoids a heavyweight dependency for twenty lines of arithmetic.
    """
    pos = sum(labels)
    neg = len(labels) - pos
    if pos == 0 or neg == 0:
        return 0.5

    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1

    rank_sum = sum(r for r, lab in zip(ranks, labels) if lab)
    return (rank_sum - pos * (pos + 1) / 2.0) / (pos * neg)


# ------------------------------------------------------------------ fitting
@dataclass
class FitReport:
    skill: str
    fitted: BKTParams
    default: BKTParams
    fitted_auc: float
    default_auc: float
    n_train: int
    n_test: int
    fitted_ll: float = 0.0
    default_ll: float = 0.0
    """Held-out mean log-likelihood per observation.

    Reported alongside AUC because the two measure different things and disagree here.
    AUC is RANK-BASED and scale-invariant: it only asks whether students are ordered
    correctly, so wildly miscalibrated parameters can score just as well. Likelihood
    measures calibration -- whether the predicted probabilities are actually right.
    Fitting optimises likelihood, so judging it only by AUC understates it. This is
    also the honest explanation for why adopting fitted parameters is not worthwhile
    HERE: the system consumes mastery as a threshold comparison, which cares about
    ranking, not calibration."""

    @property
    def improvement(self) -> float:
        return self.fitted_auc - self.default_auc

    @property
    def ll_improvement(self) -> float:
        return self.fitted_ll - self.default_ll

    @property
    def adopt(self) -> bool:
        """Adopt only on a real margin, not on noise."""
        return self.improvement > 0.01

    def line(self) -> str:
        verdict = "ADOPT fitted" if self.adopt else "KEEP defaults"
        return (
            f"  {self.skill:<22} AUC {self.default_auc:.3f}->{self.fitted_auc:.3f} "
            f"({self.improvement:+.3f})  |  logLik {self.default_ll:.4f}->{self.fitted_ll:.4f} "
            f"({self.ll_improvement:+.4f})  ->  {verdict}"
        )


_GRID = {
    "p_init": [0.05, 0.15, 0.25, 0.35, 0.5],
    "p_transit": [0.05, 0.1, 0.15, 0.25, 0.4],
    "p_slip": [0.05, 0.1, 0.2, 0.3],
    "p_guess": [0.1, 0.2, 0.3, 0.4],
}


def fit(sequences: list[Sequence]) -> BKTParams:
    """Maximise total log-likelihood over the parameter grid, then refine locally."""
    best = BKTParams()
    best_ll = float("-inf")

    for pi, pt, ps, pg in product(*_GRID.values()):
        if ps + pg >= 1.0:
            continue  # degenerate / non-identifiable
        try:
            cand = BKTParams(p_init=pi, p_transit=pt, p_slip=ps, p_guess=pg)
        except ValueError:
            continue
        ll = sum(sequence_log_likelihood(s, cand) for s in sequences)
        if ll > best_ll:
            best_ll, best = ll, cand

    # local refinement around the grid winner
    for _ in range(3):
        improved = False
        for name, delta in product(
            ("p_init", "p_transit", "p_slip", "p_guess"), (-0.04, 0.04)
        ):
            value = getattr(best, name) + delta
            if not 0.01 < value < 0.99:
                continue
            kwargs = {
                "p_init": best.p_init,
                "p_transit": best.p_transit,
                "p_slip": best.p_slip,
                "p_guess": best.p_guess,
                name: value,
            }
            if kwargs["p_slip"] + kwargs["p_guess"] >= 1.0:
                continue
            try:
                cand = BKTParams(**kwargs)
            except ValueError:
                continue
            ll = sum(sequence_log_likelihood(s, cand) for s in sequences)
            if ll > best_ll:
                best_ll, best, improved = ll, cand, True
        if not improved:
            break
    return best


def mean_log_likelihood(sequences: list[Sequence], prm: BKTParams) -> float:
    """Held-out mean log-likelihood per observation -- the quantity fitting maximises."""
    total = sum(sequence_log_likelihood(s, prm) for s in sequences)
    n = sum(len(s) for s in sequences)
    return total / max(n, 1)


def evaluate(sequences: list[Sequence], prm: BKTParams) -> float:
    """Held-out AUC: predict the LAST answer from everything before it."""
    scores: list[float] = []
    labels: list[bool] = []
    for seq in sequences:
        if len(seq) < 2:
            continue
        scores.append(predict_next(seq[:-1], prm))
        labels.append(seq[-1])
    return auc(scores, labels)


def generate_trajectories(
    skill: str, n: int = 400, length: int = 12, seed: int = 20260913
) -> list[Sequence]:
    """Trajectories from the SIMULATOR -- deliberately not from a BKT process."""
    from app.mastery.skill_graph import SkillGraph
    from eval.simulator import SimConfig, SimulatedStudent

    from pathlib import Path

    rng = random.Random(seed)
    nodes = SkillGraph.from_yaml(Path("app/config/skills.yaml")).nodes
    graph = SkillGraph(nodes)

    sequences: list[Sequence] = []
    for i in range(n):
        true_skill = {s: rng.uniform(0.55, 0.95) for s in nodes}
        true_skill[skill] = rng.uniform(0.05, 0.5)
        # a third of the cohort also carries a prerequisite gap, so the data contains
        # the gated regime BKT has no way to represent
        if i % 3 == 0:
            for prereq in graph.prerequisites(skill):
                true_skill[prereq] = rng.uniform(0.1, 0.45)

        student = SimulatedStudent(
            true_skill=true_skill,
            graph=graph,
            config=SimConfig(),
            rng=random.Random(seed + i * 7919),
        )
        sequences.append([student.attempt(skill) for _ in range(length)])
    return sequences


def fit_and_report(skill: str, n: int = 400, seed: int = 20260913) -> FitReport:
    """Fit on a training split, judge on a held-out split."""
    sequences = generate_trajectories(skill, n=n, seed=seed)
    split = int(len(sequences) * 0.7)
    train, test = sequences[:split], sequences[split:]

    default = BKTParams()
    fitted = fit(train)
    return FitReport(
        skill=skill,
        fitted=fitted,
        default=default,
        fitted_auc=evaluate(test, fitted),
        default_auc=evaluate(test, default),
        n_train=len(train),
        n_test=len(test),
        fitted_ll=mean_log_likelihood(test, fitted),
        default_ll=mean_log_likelihood(test, default),
    )
