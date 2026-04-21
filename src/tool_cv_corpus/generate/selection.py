"""Target-aware selection (v0.2 M3).

Given a scored ``Corpus`` and a ``Target``, pick the subset of roles,
achievements, skills, and claims that the renderer should include.
Output is a ``Selection`` of IDs only: the ``Corpus`` remains the single
source of truth for entity and claim bodies, so a bug in selection
never silently rewrites the record.

Selection rules:

1. **Roles** — chronological, newest first, capped by
   ``budget.max_roles``.
2. **Achievements per role** — ranked by the best score of any claim
   attached to each achievement, capped by
   ``budget.max_achievements_per_role``.
3. **Skills** — ranked by direct match with ``Target.emphasis_skill_ids``
   (strong), then ancestor match via ``Skill.parent_id`` (weaker).
   Skills in ``Target.avoid_skill_ids`` (or whose ancestor is) are
   excluded. When both a skill and one of its ancestors survive, the
   leaf wins; the ancestor is dropped because a reader learns more
   from "django" than from "python" when both would otherwise appear.
4. **Summary claims** — ``impact`` or ``outcome`` type only, ranked
   across all subjects, capped by ``budget.max_summary_claims``.
5. **Per-subject claims** — for each selected role, achievement, and
   skill, take the top ``budget.max_claims_per_subject`` claims by
   score.
6. **Char budget** — a best-effort post-trim: if total chars across
   all selected claims exceeds ``budget.total_claim_char_limit``, drop
   the lowest-scoring claims until under the cap. Per-section caps do
   most of the work; this belt-and-suspenders step catches pathologies
   like one 800-word context claim.

Hard constraints inherited from the loader: redacted entities and
claims are already absent from ``corpus``, so they cannot be selected.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from ..schema import Claim, Target
from ..schema.claims import ClaimType
from ..schema.entities import Skill
from .loader import Corpus, EntityKey
from .scoring import ScoreBreakdown

_SUMMARY_CLAIM_TYPES: frozenset[ClaimType] = frozenset({"impact", "outcome"})


@dataclass(frozen=True)
class SelectionBudget:
    """Per-section caps for what the rendered resume can contain.

    Values are upper bounds; the selector may return fewer entries when
    the corpus simply lacks qualifying entities. All caps are tunable
    per-target so a dense senior CV can loosen defaults.
    """

    max_roles: int = 5
    max_achievements_per_role: int = 3
    max_skills: int = 20
    max_summary_claims: int = 6
    max_claims_per_subject: int = 3
    total_claim_char_limit: int = 4500


@dataclass(frozen=True)
class Selection:
    """IDs picked for inclusion in the rendered resume.

    Only identifiers, never bodies: the synthesis layer (M4) walks back
    to the ``Corpus`` with these IDs to look up the actual text. Keeping
    the selection body-free means a later re-run with the same selection
    but a fresher corpus automatically sees updated prose.
    """

    summary_claim_ids: tuple[str, ...]
    role_ids: tuple[str, ...]
    achievement_ids_by_role: Mapping[str, tuple[str, ...]]
    skill_ids: tuple[str, ...]
    claim_ids_by_subject: Mapping[EntityKey, tuple[str, ...]]


def _total(scores: Mapping[str, ScoreBreakdown], claim_id: str) -> float:
    sb = scores.get(claim_id)
    return sb.total if sb is not None else 0.0


def _ranked_claim_ids(
    claims: tuple[Claim, ...],
    scores: Mapping[str, ScoreBreakdown],
) -> list[str]:
    """Claim IDs best-first, tie-broken by claim_id for determinism."""
    return sorted((c.id for c in claims), key=lambda cid: (-_total(scores, cid), cid))


def _achievement_score(
    corpus: Corpus,
    achievement_id: str,
    scores: Mapping[str, ScoreBreakdown],
) -> float:
    """Best claim score attached to this achievement, or ``0.0`` if none.

    Using ``0.0`` (not ``-inf``) keeps an achievement with no claims
    eligible for the tail of a role's top-k, which matches how a human
    reader evaluates early-career resumes without extensive claim data.
    """
    claims = corpus.claims_for("achievement", achievement_id)
    if not claims:
        return 0.0
    return max(_total(scores, c.id) for c in claims)


def _skill_score(skill: Skill, target: Target, corpus: Corpus) -> float:
    """Relevance of a skill for the target.

    Returns a strong negative for direct or ancestor avoid matches so
    the caller can filter non-positive skills out. Direct emphasis
    match beats ancestor-only match so a leaf-specific skill surfaces
    ahead of a generic parent at equal context.
    """
    emphasis = set(target.emphasis_skill_ids)
    avoid = set(target.avoid_skill_ids)

    if skill.id in avoid:
        return -100.0

    # Walk ancestors once, checking both avoid and emphasis.
    ancestor_emphasis = False
    cur_id = skill.parent_id
    seen: set[str] = {skill.id}
    while cur_id is not None and cur_id not in seen:
        seen.add(cur_id)
        if cur_id in avoid:
            return -50.0
        if cur_id in emphasis:
            ancestor_emphasis = True
        cur = corpus.skills_by_id.get(cur_id)
        if cur is None:
            break
        cur_id = cur.parent_id

    if skill.id in emphasis:
        return 5.0
    if ancestor_emphasis:
        return 2.0
    return 0.0


def _is_ancestor(ancestor: Skill, candidate: Skill, corpus: Corpus) -> bool:
    """True if ``candidate`` transitively descends from ``ancestor``."""
    cur_id = candidate.parent_id
    seen: set[str] = set()
    while cur_id is not None and cur_id not in seen:
        if cur_id == ancestor.id:
            return True
        seen.add(cur_id)
        cur = corpus.skills_by_id.get(cur_id)
        if cur is None:
            return False
        cur_id = cur.parent_id
    return False


def _prefer_leaf_skills(selected: list[Skill], corpus: Corpus) -> list[Skill]:
    """Drop every skill that has a descendant also in ``selected``.

    ``python`` (parent) is dropped when ``django`` (child) is also
    selected: the child is a more specific signal for the reader.
    """
    result: list[Skill] = []
    for skill in selected:
        has_descendant = any(
            _is_ancestor(skill, other, corpus)
            for other in selected
            if other.id != skill.id
        )
        if not has_descendant:
            result.append(skill)
    return result


def _index_claims_by_id(corpus: Corpus) -> dict[str, Claim]:
    out: dict[str, Claim] = {}
    for claims in corpus.claims_by_subject.values():
        for claim in claims:
            out[claim.id] = claim
    return out


def select(
    corpus: Corpus,
    target: Target,
    scores: Mapping[str, ScoreBreakdown],
    budget: SelectionBudget | None = None,
) -> Selection:
    """Return a ``Selection`` under ``budget`` caps.

    Deterministic for fixed inputs; tie-broken on entity and claim IDs.
    Redaction is already applied in the ``Corpus`` so this function
    cannot emit a visibility-excluded entity or claim.
    """
    if budget is None:
        budget = SelectionBudget()

    claim_by_id = _index_claims_by_id(corpus)

    # 1. Roles: chronological, capped.
    all_roles = corpus.roles_chronological()
    selected_roles = all_roles[: budget.max_roles]
    role_ids = tuple(r.id for r in selected_roles)

    # 2. Achievements per role: top-k by best claim-score per achievement.
    achievement_ids_by_role: dict[str, tuple[str, ...]] = {}
    for role in selected_roles:
        ach_ids = [
            aid
            for aid in role.achievement_ids
            if ("achievement", aid) in corpus.entities
        ]
        ranked = sorted(
            ach_ids,
            key=lambda aid: (-_achievement_score(corpus, aid, scores), aid),
        )
        achievement_ids_by_role[role.id] = tuple(
            ranked[: budget.max_achievements_per_role]
        )

    # 3. Skills: rank, drop non-positive, prefer leaves, cap.
    ranked_skills = sorted(
        corpus.skills_by_id.values(),
        key=lambda s: (-_skill_score(s, target, corpus), s.id),
    )
    positive = [s for s in ranked_skills if _skill_score(s, target, corpus) > 0.0]
    # When no emphasis hits anything, fall back to neutral skills so the
    # resume still has a skills section; avoid-matches (negative scores)
    # are excluded either way.
    if not positive:
        positive = [s for s in ranked_skills if _skill_score(s, target, corpus) >= 0.0]
    deduped = _prefer_leaf_skills(positive, corpus)
    skill_ids = tuple(s.id for s in deduped[: budget.max_skills])

    # 4. Summary claims: top impact/outcome across corpus.
    summary_candidates: list[tuple[str, float]] = []
    for claims in corpus.claims_by_subject.values():
        for claim in claims:
            if claim.type in _SUMMARY_CLAIM_TYPES:
                summary_candidates.append((claim.id, _total(scores, claim.id)))
    summary_candidates.sort(key=lambda t: (-t[1], t[0]))
    summary_claim_ids = tuple(
        cid for cid, _ in summary_candidates[: budget.max_summary_claims]
    )

    # 5. Per-subject ranked claims for every selected subject.
    selected_subjects: set[EntityKey] = set()
    for rid in role_ids:
        selected_subjects.add(("role", rid))
    for aids in achievement_ids_by_role.values():
        for aid in aids:
            selected_subjects.add(("achievement", aid))
    for sid in skill_ids:
        selected_subjects.add(("skill", sid))

    claim_ids_by_subject: dict[EntityKey, tuple[str, ...]] = {}
    for subj in selected_subjects:
        claims = corpus.claims_by_subject.get(subj, ())
        if not claims:
            continue
        ranked = _ranked_claim_ids(claims, scores)
        claim_ids_by_subject[subj] = tuple(ranked[: budget.max_claims_per_subject])

    # 6. Char-budget trim: drop globally lowest-scoring claims until
    # under cap, summary claims protected from the first wave.
    summary_claim_ids, claim_ids_by_subject = _trim_to_char_budget(
        summary_claim_ids=summary_claim_ids,
        claim_ids_by_subject=claim_ids_by_subject,
        claim_by_id=claim_by_id,
        scores=scores,
        char_limit=budget.total_claim_char_limit,
    )

    return Selection(
        summary_claim_ids=summary_claim_ids,
        role_ids=role_ids,
        achievement_ids_by_role=MappingProxyType(dict(achievement_ids_by_role)),
        skill_ids=skill_ids,
        claim_ids_by_subject=MappingProxyType(dict(claim_ids_by_subject)),
    )


def _trim_to_char_budget(
    *,
    summary_claim_ids: tuple[str, ...],
    claim_ids_by_subject: dict[EntityKey, tuple[str, ...]],
    claim_by_id: Mapping[str, Claim],
    scores: Mapping[str, ScoreBreakdown],
    char_limit: int,
) -> tuple[tuple[str, ...], dict[EntityKey, tuple[str, ...]]]:
    """Drop lowest-scoring per-subject claims, then summary claims, until
    the total character count of selected claims fits ``char_limit``.

    Summary claims go last because they anchor the top of the resume;
    losing the bottom bullet of a role is a smaller hit to the reader
    than losing the summary headline's supporting evidence.
    """

    def _chars(cid: str) -> int:
        claim = claim_by_id.get(cid)
        return len(claim.text) if claim is not None else 0

    all_ids: list[str] = list(summary_claim_ids)
    for cids in claim_ids_by_subject.values():
        all_ids.extend(cids)

    total = sum(_chars(cid) for cid in all_ids)
    if total <= char_limit:
        return summary_claim_ids, claim_ids_by_subject

    # Drop per-subject claims first, lowest score first, tie-break by ID.
    subject_claims: list[tuple[str, float, EntityKey]] = [
        (cid, _total(scores, cid), subj)
        for subj, cids in claim_ids_by_subject.items()
        for cid in cids
    ]
    subject_claims.sort(key=lambda t: (t[1], t[0]))

    dropped: set[str] = set()
    for cid, _, _ in subject_claims:
        if total <= char_limit:
            break
        total -= _chars(cid)
        dropped.add(cid)

    new_by_subject = {
        subj: tuple(c for c in cids if c not in dropped)
        for subj, cids in claim_ids_by_subject.items()
    }
    new_by_subject = {subj: cids for subj, cids in new_by_subject.items() if cids}

    if total <= char_limit:
        return summary_claim_ids, new_by_subject

    # Still over; now drop summary claims lowest-score first.
    summary_ranked = sorted(
        summary_claim_ids, key=lambda cid: (_total(scores, cid), cid)
    )
    for cid in summary_ranked:
        if total <= char_limit:
            break
        total -= _chars(cid)
        dropped.add(cid)

    new_summary = tuple(c for c in summary_claim_ids if c not in dropped)
    return new_summary, new_by_subject
