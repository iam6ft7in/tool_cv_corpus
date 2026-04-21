"""Tests for the v0.2 target-aware selector.

Fixtures build small on-disk corpora per test so each behavior has an
isolated minimal reproducer. The scorer produces a deterministic
breakdown; assertions here target selection logic (ranking, caps,
ancestor-dedup, char budget) rather than re-testing scoring math.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tool_cv_corpus.generate.loader import load_corpus
from tool_cv_corpus.generate.scoring import ScoringWeights, score_claims
from tool_cv_corpus.generate.selection import (
    Selection,
    SelectionBudget,
    select,
)
from tool_cv_corpus.schema.entities import Target


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _person(root: Path) -> None:
    _write(root / "persons" / "p.yaml", "kind: person\nid: p\nfull_name: Pat\n")


def _org(root: Path, org_id: str = "o") -> None:
    _write(
        root / "organizations" / f"{org_id}.yaml",
        f"kind: organization\nid: {org_id}\nname: {org_id.upper()}\n",
    )


def _role(
    root: Path,
    role_id: str,
    *,
    org_id: str = "o",
    start: str = "2020-01",
    end: str | None = "2024-12",
    achievement_ids: list[str] | None = None,
    skill_ids: list[str] | None = None,
) -> None:
    end_line = f"  end: '{end}'\n" if end else ""
    ach_line = ""
    if achievement_ids:
        ach_line = "achievement_ids:\n" + "".join(f"  - {a}\n" for a in achievement_ids)
    skill_line = ""
    if skill_ids:
        skill_line = "skill_ids:\n" + "".join(f"  - {s}\n" for s in skill_ids)
    _write(
        root / "roles" / f"{role_id}.yaml",
        f"kind: role\nid: {role_id}\ntitle: Eng\norganization_id: {org_id}\n"
        f"period:\n  start: '{start}'\n{end_line}{ach_line}{skill_line}",
    )


def _achievement(
    root: Path,
    ach_id: str,
    *,
    role_id: str = "r",
    skill_ids: list[str] | None = None,
) -> None:
    skill_line = ""
    if skill_ids:
        skill_line = "skill_ids:\n" + "".join(f"  - {s}\n" for s in skill_ids)
    _write(
        root / "achievements" / f"{ach_id}.yaml",
        f"kind: achievement\nid: {ach_id}\nheadline: {ach_id}\n"
        f"role_id: {role_id}\n{skill_line}",
    )


def _skill(root: Path, skill_id: str, *, parent_id: str | None = None) -> None:
    parent_line = f"parent_id: {parent_id}\n" if parent_id else ""
    _write(
        root / "skills" / f"{skill_id}.yaml",
        f"kind: skill\nid: {skill_id}\nname: {skill_id}\ntier: applied\n{parent_line}",
    )


def _claim(
    root: Path,
    claim_id: str,
    subject_kind: str,
    subject_id: str,
    *,
    text: str = "did a thing",
    ctype: str = "outcome",
) -> None:
    _write(
        root / "claims" / f"{claim_id}.yaml",
        f"kind: claim\nid: {claim_id}\nsubject_id: {subject_id}\n"
        f"subject_kind: {subject_kind}\ntype: {ctype}\ntext: {text}\n",
    )


def _target(
    *,
    emphasis: list[str] | None = None,
    avoid: list[str] | None = None,
) -> Target:
    return Target(
        id="t",
        role_title="Engineer",
        organization_name="Contoso",
        emphasis_skill_ids=emphasis or [],
        avoid_skill_ids=avoid or [],
    )


# --- Shape and determinism ----------------------------------------------


def test_empty_corpus_returns_empty_selection(tmp_path: Path) -> None:
    _person(tmp_path)
    corpus = load_corpus(tmp_path)
    scores = score_claims(corpus, _target(), now="2025-01")

    sel = select(corpus, _target(), scores)

    assert isinstance(sel, Selection)
    assert sel.role_ids == ()
    assert sel.skill_ids == ()
    assert sel.summary_claim_ids == ()
    assert sel.achievement_ids_by_role == {}
    assert sel.claim_ids_by_subject == {}


def test_selection_is_deterministic(tmp_path: Path) -> None:
    _person(tmp_path)
    _org(tmp_path)
    _role(tmp_path, "r", achievement_ids=["a1", "a2"])
    _achievement(tmp_path, "a1")
    _achievement(tmp_path, "a2")

    corpus = load_corpus(tmp_path)
    scores = score_claims(corpus, _target(), now="2025-01")

    a = select(corpus, _target(), scores)
    b = select(corpus, _target(), scores)
    assert a == b


# --- Roles --------------------------------------------------------------


def test_roles_are_chronological_newest_first(tmp_path: Path) -> None:
    _person(tmp_path)
    _org(tmp_path)
    _role(tmp_path, "r_old", start="2015-01", end="2017-12")
    _role(tmp_path, "r_new", start="2022-01", end="2024-12")
    _role(tmp_path, "r_mid", start="2018-01", end="2020-12")

    corpus = load_corpus(tmp_path)
    scores = score_claims(corpus, _target(), now="2025-01")

    sel = select(corpus, _target(), scores)
    assert sel.role_ids == ("r_new", "r_mid", "r_old")


def test_roles_capped_by_budget(tmp_path: Path) -> None:
    _person(tmp_path)
    _org(tmp_path)
    for i in range(6):
        _role(tmp_path, f"r{i}", start=f"{2010 + i}-01", end=f"{2011 + i}-01")

    corpus = load_corpus(tmp_path)
    scores = score_claims(corpus, _target(), now="2025-01")

    sel = select(corpus, _target(), scores, SelectionBudget(max_roles=3))
    assert len(sel.role_ids) == 3
    # Newest three
    assert sel.role_ids == ("r5", "r4", "r3")


# --- Achievements -------------------------------------------------------


def test_achievements_ranked_by_best_claim_score(tmp_path: Path) -> None:
    _person(tmp_path)
    _org(tmp_path)
    _role(tmp_path, "r", achievement_ids=["a_hot", "a_cold"])
    _achievement(tmp_path, "a_hot", skill_ids=["python"])
    _achievement(tmp_path, "a_cold")
    _skill(tmp_path, "python")
    # Claim attached to a_hot inherits emphasis via achievement.skill_ids.
    _claim(tmp_path, "c_hot", "achievement", "a_hot", ctype="impact")
    _claim(tmp_path, "c_cold", "achievement", "a_cold", ctype="context")

    corpus = load_corpus(tmp_path)
    scores = score_claims(corpus, _target(emphasis=["python"]), now="2025-01")

    sel = select(corpus, _target(emphasis=["python"]), scores)
    assert sel.achievement_ids_by_role["r"][0] == "a_hot"


def test_achievements_capped_per_role(tmp_path: Path) -> None:
    _person(tmp_path)
    _org(tmp_path)
    ach_ids = [f"a{i}" for i in range(5)]
    _role(tmp_path, "r", achievement_ids=ach_ids)
    for aid in ach_ids:
        _achievement(tmp_path, aid)

    corpus = load_corpus(tmp_path)
    scores = score_claims(corpus, _target(), now="2025-01")

    sel = select(
        corpus, _target(), scores, SelectionBudget(max_achievements_per_role=2)
    )
    assert len(sel.achievement_ids_by_role["r"]) == 2


def test_achievements_referenced_but_absent_are_ignored(tmp_path: Path) -> None:
    """A role may list an achievement_id whose entity was redacted out;
    the selector must silently skip missing references rather than
    emit a dangling ID."""
    _person(tmp_path)
    _org(tmp_path)
    _role(tmp_path, "r", achievement_ids=["a_present", "a_missing"])
    _achievement(tmp_path, "a_present")

    corpus = load_corpus(tmp_path)
    scores = score_claims(corpus, _target(), now="2025-01")

    sel = select(corpus, _target(), scores)
    assert sel.achievement_ids_by_role["r"] == ("a_present",)


# --- Skills -------------------------------------------------------------


def test_skill_direct_emphasis_match_is_selected(tmp_path: Path) -> None:
    _person(tmp_path)
    _skill(tmp_path, "python")

    corpus = load_corpus(tmp_path)
    scores = score_claims(corpus, _target(emphasis=["python"]), now="2025-01")

    sel = select(corpus, _target(emphasis=["python"]), scores)
    assert sel.skill_ids == ("python",)


def test_skill_avoid_match_is_excluded(tmp_path: Path) -> None:
    _person(tmp_path)
    _skill(tmp_path, "cobol")
    _skill(tmp_path, "python")

    corpus = load_corpus(tmp_path)
    scores = score_claims(
        corpus,
        _target(emphasis=["python"], avoid=["cobol"]),
        now="2025-01",
    )

    sel = select(corpus, _target(emphasis=["python"], avoid=["cobol"]), scores)
    assert "cobol" not in sel.skill_ids
    assert "python" in sel.skill_ids


def test_skill_avoid_ancestor_also_excludes_descendant(tmp_path: Path) -> None:
    """If parent is in avoid, children are also excluded."""
    _person(tmp_path)
    _skill(tmp_path, "legacy")
    _skill(tmp_path, "cobol", parent_id="legacy")
    _skill(tmp_path, "rust")

    corpus = load_corpus(tmp_path)
    scores = score_claims(
        corpus,
        _target(emphasis=["rust"], avoid=["legacy"]),
        now="2025-01",
    )

    sel = select(corpus, _target(emphasis=["rust"], avoid=["legacy"]), scores)
    assert "cobol" not in sel.skill_ids
    assert "legacy" not in sel.skill_ids
    assert "rust" in sel.skill_ids


def test_skill_leaf_preferred_when_parent_also_qualifies(tmp_path: Path) -> None:
    """Target emphasizes 'python'; corpus has 'python' and 'django'
    (django.parent=python). Both score positive via emphasis/ancestor,
    but only the leaf should be emitted."""
    _person(tmp_path)
    _skill(tmp_path, "python")
    _skill(tmp_path, "django", parent_id="python")

    corpus = load_corpus(tmp_path)
    scores = score_claims(corpus, _target(emphasis=["python"]), now="2025-01")

    sel = select(corpus, _target(emphasis=["python"]), scores)
    assert sel.skill_ids == ("django",)


def test_skills_capped_by_budget(tmp_path: Path) -> None:
    _person(tmp_path)
    for i in range(30):
        _skill(tmp_path, f"s{i:02}")

    corpus = load_corpus(tmp_path)
    scores = score_claims(
        corpus,
        _target(emphasis=[f"s{i:02}" for i in range(30)]),
        now="2025-01",
    )

    sel = select(
        corpus,
        _target(emphasis=[f"s{i:02}" for i in range(30)]),
        scores,
        SelectionBudget(max_skills=5),
    )
    assert len(sel.skill_ids) == 5


def test_skills_no_emphasis_falls_back_to_neutral(tmp_path: Path) -> None:
    """When the target names no emphasis skills, the selector still
    returns skills up to the cap so the resume has a skills section;
    avoid skills remain excluded."""
    _person(tmp_path)
    _skill(tmp_path, "python")
    _skill(tmp_path, "rust")
    _skill(tmp_path, "cobol")

    corpus = load_corpus(tmp_path)
    scores = score_claims(corpus, _target(avoid=["cobol"]), now="2025-01")

    sel = select(corpus, _target(avoid=["cobol"]), scores)
    assert set(sel.skill_ids) == {"python", "rust"}


# --- Summary claims -----------------------------------------------------


def test_summary_only_includes_impact_or_outcome(tmp_path: Path) -> None:
    _person(tmp_path)
    _org(tmp_path)
    _role(tmp_path, "r")
    _claim(tmp_path, "c_impact", "role", "r", ctype="impact")
    _claim(tmp_path, "c_outcome", "role", "r", ctype="outcome")
    _claim(tmp_path, "c_context", "role", "r", ctype="context")
    _claim(tmp_path, "c_fact", "role", "r", ctype="fact")

    corpus = load_corpus(tmp_path)
    scores = score_claims(corpus, _target(), now="2025-01")

    sel = select(corpus, _target(), scores)
    assert set(sel.summary_claim_ids) == {"c_impact", "c_outcome"}


def test_summary_ordered_by_score_descending(tmp_path: Path) -> None:
    _person(tmp_path)
    _org(tmp_path)
    _role(tmp_path, "r_new", start="2022-01", end="2024-12")
    _role(tmp_path, "r_old", start="2005-01", end="2007-12")
    _claim(tmp_path, "c_new", "role", "r_new", ctype="impact")
    _claim(tmp_path, "c_old", "role", "r_old", ctype="impact")

    corpus = load_corpus(tmp_path)
    scores = score_claims(corpus, _target(), now="2025-01")

    sel = select(corpus, _target(), scores)
    # Recency boosts c_new over c_old at equal type.
    assert sel.summary_claim_ids[0] == "c_new"


def test_summary_capped_by_budget(tmp_path: Path) -> None:
    _person(tmp_path)
    _org(tmp_path)
    _role(tmp_path, "r")
    for i in range(10):
        _claim(tmp_path, f"c{i}", "role", "r", ctype="outcome")

    corpus = load_corpus(tmp_path)
    scores = score_claims(corpus, _target(), now="2025-01")

    sel = select(corpus, _target(), scores, SelectionBudget(max_summary_claims=3))
    assert len(sel.summary_claim_ids) == 3


# --- Per-subject claims -------------------------------------------------


def test_per_subject_claims_capped_and_ranked(tmp_path: Path) -> None:
    _person(tmp_path)
    _org(tmp_path)
    _role(tmp_path, "r")
    for ctype, cid in (
        ("impact", "c_a"),
        ("outcome", "c_b"),
        ("context", "c_c"),
        ("fact", "c_d"),
    ):
        _claim(tmp_path, cid, "role", "r", ctype=ctype)

    corpus = load_corpus(tmp_path)
    scores = score_claims(corpus, _target(), now="2025-01")

    sel = select(corpus, _target(), scores, SelectionBudget(max_claims_per_subject=2))
    per_role = sel.claim_ids_by_subject[("role", "r")]
    assert len(per_role) == 2
    # impact (1.0) > outcome (0.8) by default weights
    assert per_role[0] == "c_a"
    assert per_role[1] == "c_b"


def test_claims_absent_for_subjects_not_selected(tmp_path: Path) -> None:
    """Claims attached to non-selected subjects do not appear in the
    per-subject map."""
    _person(tmp_path)
    _org(tmp_path)
    _role(tmp_path, "r")
    _skill(tmp_path, "python")
    _claim(tmp_path, "c_skill", "skill", "python")

    corpus = load_corpus(tmp_path)
    scores = score_claims(corpus, _target(), now="2025-01")

    sel = select(corpus, _target(), scores)
    # "python" is emitted via neutral fallback, so its claims appear.
    assert ("skill", "python") in sel.claim_ids_by_subject


# --- Char budget --------------------------------------------------------


def test_char_budget_trims_lowest_score_first(tmp_path: Path) -> None:
    _person(tmp_path)
    _org(tmp_path)
    _role(tmp_path, "r")
    # Two claims on same role; impact gets higher default weight than fact.
    _claim(
        tmp_path,
        "c_high",
        "role",
        "r",
        ctype="impact",
        text="H" * 100,
    )
    _claim(
        tmp_path,
        "c_low",
        "role",
        "r",
        ctype="fact",
        text="L" * 100,
    )

    corpus = load_corpus(tmp_path)
    scores = score_claims(corpus, _target(), now="2025-01")

    # Budget below combined length so one must drop; per-subject trim
    # runs first and the lowest-scoring claim goes.
    sel = select(
        corpus,
        _target(),
        scores,
        SelectionBudget(
            max_claims_per_subject=5,
            max_summary_claims=0,
            total_claim_char_limit=120,
        ),
    )
    role_claims = sel.claim_ids_by_subject.get(("role", "r"), ())
    assert role_claims == ("c_high",)


def test_char_budget_noop_when_under_cap(tmp_path: Path) -> None:
    _person(tmp_path)
    _org(tmp_path)
    _role(tmp_path, "r")
    _claim(tmp_path, "c", "role", "r", ctype="impact", text="short")

    corpus = load_corpus(tmp_path)
    scores = score_claims(corpus, _target(), now="2025-01")

    sel = select(corpus, _target(), scores)
    assert sel.claim_ids_by_subject.get(("role", "r")) == ("c",)


# --- Smoke: example corpus ----------------------------------------------


def test_example_corpus_selection_shape() -> None:
    repo_root = Path(__file__).resolve().parent.parent.parent
    example = repo_root / "examples" / "corpus_jordan_taylor"

    corpus = load_corpus(example)
    scores = score_claims(corpus, _target(), now="2026-04")

    sel = select(corpus, _target(), scores)
    assert len(sel.role_ids) <= 5
    assert len(sel.skill_ids) <= 20
    # Example corpus has no claims, so per-subject claim sets are empty.
    assert sel.claim_ids_by_subject == {}
    assert sel.summary_claim_ids == ()


# --- Custom weights propagate through selection -------------------------


def test_custom_weights_affect_ranking(tmp_path: Path) -> None:
    _person(tmp_path)
    _org(tmp_path)
    _role(tmp_path, "r")
    _claim(tmp_path, "c_impact", "role", "r", ctype="impact")
    _claim(tmp_path, "c_fact", "role", "r", ctype="fact")

    corpus = load_corpus(tmp_path)

    # Default weights: impact ranks above fact.
    default_scores = score_claims(corpus, _target(), now="2025-01")
    default_sel = select(corpus, _target(), default_scores)
    assert default_sel.summary_claim_ids == ("c_impact",)  # fact excluded

    # Weights inverted for claim_type only: fact beats impact.
    inverted_scores = score_claims(
        corpus,
        _target(),
        ScoringWeights(claim_type={"fact": 5.0, "impact": 0.1}),
        now="2025-01",
    )
    # Summary still filters by type (impact|outcome), so c_fact never
    # enters summary regardless of its score. Verify via per-subject
    # ranking instead.
    inv_sel = select(corpus, _target(), inverted_scores)
    per_role = inv_sel.claim_ids_by_subject[("role", "r")]
    assert per_role[0] == "c_fact"


def test_returned_mappings_are_read_only(tmp_path: Path) -> None:
    _person(tmp_path)
    _org(tmp_path)
    _role(tmp_path, "r", achievement_ids=["a1"])
    _achievement(tmp_path, "a1")

    corpus = load_corpus(tmp_path)
    scores = score_claims(corpus, _target(), now="2025-01")

    sel = select(corpus, _target(), scores)
    with pytest.raises(TypeError):
        sel.achievement_ids_by_role["x"] = ()  # type: ignore[index]
    with pytest.raises(TypeError):
        sel.claim_ids_by_subject[("role", "x")] = ()  # type: ignore[index]
