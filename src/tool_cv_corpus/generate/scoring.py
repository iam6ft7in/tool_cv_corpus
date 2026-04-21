"""Claim scorer: rule-based, additive, interpretable (v0.2 M2).

Given a ``Corpus`` and a ``Target``, assign each active claim a numeric
score reflecting how well it fits the target. Higher is better.

Every claim returns a per-signal breakdown, not just a total, so a future
``--explain`` view can surface *why* a claim ranked where it did and so
tests can isolate one signal without being polluted by others. Signals
used:

- ``emphasis_skill_overlap``: subject's own skill_ids (or any ancestor
  via ``Skill.parent_id``) intersect ``Target.emphasis_skill_ids``.
  Scored per match, so three matches beats one.
- ``avoid_skill_overlap``: same logic for ``Target.avoid_skill_ids``;
  a strong negative because the user has said "do not surface."
- ``claim_type``: per-type constant so ``impact`` outranks ``context``
  by default even at equal recency.
- ``sourced``: small bonus for claims with at least one ``SourceDoc``.
- ``recency``: exponential decay on the most recent date attached to
  the subject (role.period.end, achievement.date, skill.last_used,
  publication.date). Open-ended periods are treated as "now" so a
  current role scores as maximally recent.

No LLM is involved here. Synthesis (M4) uses the scorer's output as a
selection input, never the reverse.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType

from ..schema import Claim, Target
from ..schema.claims import ClaimType
from ..schema.dates import PartialDate
from ..schema.entities import (
    Achievement,
    Education,
    Project,
    Publication,
    Role,
    Skill,
)
from .loader import Corpus

DEFAULT_CLAIM_TYPE_WEIGHTS: Mapping[ClaimType, float] = MappingProxyType(
    {
        "impact": 1.0,
        "outcome": 0.8,
        "responsibility": 0.4,
        "fact": 0.2,
        "context": 0.1,
        "quote": 0.3,
    }
)
"""Per-``ClaimType`` weight. Exposed so tests and alternative weight
profiles can reference it without hard-coding the floats."""


@dataclass(frozen=True)
class ScoringWeights:
    """Linear weights for each signal the scorer combines.

    All weights are independently tunable; callers can override any
    subset and rely on the defaults for the rest. Zero-weighted signals
    are skipped entirely (they do not pollute ``components`` with
    zero entries), so future signals can ship with a safe-off default.
    """

    emphasis_skill_overlap: float = 3.0
    """Per-match boost when the subject's skill set (expanded up the
    ``parent_id`` chain) intersects ``Target.emphasis_skill_ids``."""

    avoid_skill_overlap: float = -5.0
    """Per-match penalty for ``Target.avoid_skill_ids``. Stronger than
    one emphasis match by default so a single avoid-match beats three
    emphasis-matches, reflecting the user's explicit suppression intent.
    """

    sourced: float = 0.5
    """Bonus for claims with at least one ``SourceDoc`` reference;
    reviewers can audit the claim, so it is safer to lean on."""

    claim_type: Mapping[ClaimType, float] = DEFAULT_CLAIM_TYPE_WEIGHTS
    """Per-type preference. Default orders impact > outcome >
    responsibility > quote > fact > context."""

    recency_halflife_months: float = 36.0
    """Months for the recency signal to halve. 36 = a claim whose
    subject is three years old contributes half as much recency weight
    as a claim whose subject is current."""

    recency_weight: float = 1.0
    """Peak recency contribution for a subject dated today (or a
    still-open period)."""


@dataclass(frozen=True)
class ScoreBreakdown:
    """Per-claim score with per-signal contributions.

    ``components`` is a ``MappingProxyType`` so callers can trust it
    will not mutate between reads; the mapping only contains signals
    that actually contributed (non-zero), which keeps the view
    compact in the common case.
    """

    total: float
    components: Mapping[str, float]


def _partial_date_to_months(pd: PartialDate) -> int:
    """Month count since year 0 for ``PartialDate`` arithmetic.

    Day granularity is dropped because recency is a month-level concept;
    a missing month defaults to January so ``YYYY`` rounds to the start
    of the year, giving a small systematic bias towards "older than a
    year-precise date looks" which is the conservative direction for a
    freshness signal.
    """
    parts = pd.split("-")
    year = int(parts[0])
    month = int(parts[1]) if len(parts) >= 2 else 1
    return year * 12 + month


def _subject_skills(corpus: Corpus, claim: Claim) -> set[str]:
    """Skill IDs associated with a claim's subject, expanded to ancestors.

    Walks ``Skill.parent_id`` so a target emphasizing "python" matches a
    subject that lists "django" when "django.parent_id == python". Cycle
    protection is defensive: validator check c09 already rejects cyclic
    skill parents, but the scorer should not melt if a user runs it on
    an unvalidated corpus.
    """
    key = (claim.subject_kind, claim.subject_id)
    entity = corpus.entities.get(key)
    if entity is None:
        return set()

    direct: set[str] = set()
    if isinstance(entity, Skill):
        direct.add(entity.id)
    direct.update(getattr(entity, "skill_ids", None) or [])

    expanded: set[str] = set(direct)
    for skill_id in direct:
        cur = corpus.skills_by_id.get(skill_id)
        while cur is not None and cur.parent_id is not None:
            if cur.parent_id in expanded:
                break
            expanded.add(cur.parent_id)
            cur = corpus.skills_by_id.get(cur.parent_id)
    return expanded


def _subject_recency_date(
    corpus: Corpus, claim: Claim, now_pd: PartialDate
) -> PartialDate | None:
    """Most-meaningful date for recency, or ``None`` if the subject has none.

    Open-ended periods (``end is None``) resolve to ``now_pd`` so an
    ongoing role scores as maximally recent, which matches how a human
    reviewer would read a resume.
    """
    entity = corpus.entities.get((claim.subject_kind, claim.subject_id))
    if entity is None:
        return None
    if isinstance(entity, Role):
        return entity.period.end or now_pd
    if isinstance(entity, Project) and entity.period is not None:
        return entity.period.end or now_pd
    if isinstance(entity, Education) and entity.period is not None:
        return entity.period.end or now_pd
    if isinstance(entity, Achievement):
        return entity.date
    if isinstance(entity, Skill):
        return entity.last_used
    if isinstance(entity, Publication):
        return entity.date
    return None


def score_claims(
    corpus: Corpus,
    target: Target,
    weights: ScoringWeights | None = None,
    *,
    now: PartialDate | None = None,
) -> dict[str, ScoreBreakdown]:
    """Return ``{claim_id: ScoreBreakdown}`` for every claim in ``corpus``.

    Deterministic: identical ``(corpus, target, weights, now)`` inputs
    produce identical output. Pin ``now`` in tests and leave it ``None``
    in production to use today's date at ISO-month granularity.
    """
    if weights is None:
        weights = ScoringWeights()
    if now is None:
        now = date.today().isoformat()

    emphasis = set(target.emphasis_skill_ids)
    avoid = set(target.avoid_skill_ids)
    now_months = _partial_date_to_months(now)

    scores: dict[str, ScoreBreakdown] = {}
    for claims in corpus.claims_by_subject.values():
        for claim in claims:
            components: dict[str, float] = {}

            subj_skills = _subject_skills(corpus, claim)
            em_matches = len(subj_skills & emphasis)
            if em_matches and weights.emphasis_skill_overlap != 0.0:
                components["emphasis_skill_overlap"] = (
                    em_matches * weights.emphasis_skill_overlap
                )
            av_matches = len(subj_skills & avoid)
            if av_matches and weights.avoid_skill_overlap != 0.0:
                components["avoid_skill_overlap"] = (
                    av_matches * weights.avoid_skill_overlap
                )

            ct_weight = weights.claim_type.get(claim.type, 0.0)
            if ct_weight != 0.0:
                components["claim_type"] = ct_weight

            if claim.sources and weights.sourced != 0.0:
                components["sourced"] = weights.sourced

            subj_date = _subject_recency_date(corpus, claim, now)
            if subj_date is not None and weights.recency_weight != 0.0:
                months_since = max(0, now_months - _partial_date_to_months(subj_date))
                decay = 0.5 ** (months_since / weights.recency_halflife_months)
                components["recency"] = weights.recency_weight * decay

            scores[claim.id] = ScoreBreakdown(
                total=sum(components.values()),
                components=MappingProxyType(dict(components)),
            )

    return scores
