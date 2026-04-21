"""Tests for the v0.2 claim scorer.

Each test isolates one signal by zeroing out the others, so an unrelated
default-weight change cannot silently break an assertion. Fixtures are
tiny on-disk corpora written to ``tmp_path`` rather than reused across
tests, so a failure points directly at the scenario that broke.
"""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

import pytest

from tool_cv_corpus.generate.loader import load_corpus
from tool_cv_corpus.generate.scoring import (
    DEFAULT_CLAIM_TYPE_WEIGHTS,
    ScoreBreakdown,
    ScoringWeights,
    score_claims,
)
from tool_cv_corpus.schema.entities import Target

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EXAMPLE = REPO_ROOT / "examples" / "corpus_jordan_taylor"

# --- Fixture helpers -----------------------------------------------------

_ONLY_RECENCY = ScoringWeights(
    emphasis_skill_overlap=0.0,
    avoid_skill_overlap=0.0,
    sourced=0.0,
    claim_type={},
    recency_weight=1.0,
)
"""Keeps only the recency signal active, for clean recency assertions."""

_ONLY_CLAIM_TYPE = ScoringWeights(
    emphasis_skill_overlap=0.0,
    avoid_skill_overlap=0.0,
    sourced=0.0,
    recency_weight=0.0,
)
"""Keeps only the claim_type signal active."""

_ONLY_EMPHASIS = ScoringWeights(
    avoid_skill_overlap=0.0,
    sourced=0.0,
    claim_type={},
    recency_weight=0.0,
)
"""Keeps only the emphasis signal active."""

_ONLY_AVOID = ScoringWeights(
    emphasis_skill_overlap=0.0,
    sourced=0.0,
    claim_type={},
    recency_weight=0.0,
)
"""Keeps only the avoid signal active."""

_ONLY_SOURCED = ScoringWeights(
    emphasis_skill_overlap=0.0,
    avoid_skill_overlap=0.0,
    claim_type={},
    recency_weight=0.0,
)
"""Keeps only the sourced signal active."""


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _minimal_person(root: Path) -> None:
    _write(
        root / "persons" / "p.yaml",
        "kind: person\nid: p\nfull_name: Pat\n",
    )


def _target(
    ent_id: str = "t",
    *,
    emphasis: list[str] | None = None,
    avoid: list[str] | None = None,
) -> Target:
    """In-memory Target built from the schema, bypassing YAML for brevity."""
    return Target(
        id=ent_id,
        role_title="Engineer",
        organization_name="Contoso",
        emphasis_skill_ids=emphasis or [],
        avoid_skill_ids=avoid or [],
    )


def _build_role_corpus(
    root: Path,
    *,
    role_skill_ids: list[str] | None = None,
    claim_text: str = "did something",
    claim_type: str = "fact",
    claim_sources: list[str] | None = None,
    role_start: str = "2010-01",
    role_end: str | None = "2024-12",
    skills: list[tuple[str, str | None]] | None = None,
) -> None:
    """Write one Person + Organization + Role + Claim. ``skills`` entries
    are ``(skill_id, parent_id_or_None)`` pairs added as Skill entities."""
    _minimal_person(root)
    _write(
        root / "organizations" / "o.yaml",
        "kind: organization\nid: o\nname: O\n",
    )
    skill_line = ""
    if role_skill_ids:
        skill_line = "skill_ids:\n" + "".join(f"  - {s}\n" for s in role_skill_ids)
    end_line = f"  end: '{role_end}'\n" if role_end else ""
    _write(
        root / "roles" / "r.yaml",
        "kind: role\nid: r\ntitle: Engineer\norganization_id: o\n"
        "period:\n"
        f"  start: '{role_start}'\n"
        f"{end_line}"
        f"{skill_line}",
    )
    sources_line = ""
    if claim_sources:
        sources_line = "sources:\n" + "".join(f"  - {s}\n" for s in claim_sources)
    _write(
        root / "claims" / "c.yaml",
        "kind: claim\nid: c\nsubject_id: r\nsubject_kind: role\n"
        f"type: {claim_type}\n"
        f"text: {claim_text}\n"
        f"{sources_line}",
    )
    for skill_id, parent in skills or []:
        parent_line = f"parent_id: {parent}\n" if parent else ""
        _write(
            root / "skills" / f"{skill_id}.yaml",
            f"kind: skill\nid: {skill_id}\nname: {skill_id}\ntier: applied\n"
            f"{parent_line}",
        )


# --- Behavior: returns, shape, determinism ------------------------------


def test_empty_corpus_yields_no_scores(tmp_path: Path) -> None:
    _minimal_person(tmp_path)
    corpus = load_corpus(tmp_path)

    assert score_claims(corpus, _target()) == {}


def test_example_corpus_smoke() -> None:
    corpus = load_corpus(EXAMPLE)
    scores = score_claims(corpus, _target(), now="2026-04")
    # Example corpus ships with no claims today; a scorer on a claim-less
    # corpus must return an empty dict rather than erroring.
    assert scores == {}


def test_score_breakdown_components_are_read_only(tmp_path: Path) -> None:
    _build_role_corpus(tmp_path)
    corpus = load_corpus(tmp_path)
    scores = score_claims(corpus, _target(), now="2025-01")

    sb = scores["c"]
    assert isinstance(sb, ScoreBreakdown)
    assert isinstance(sb.components, MappingProxyType)
    with pytest.raises(TypeError):
        sb.components["fake"] = 1.0  # type: ignore[index]


def test_deterministic_across_runs(tmp_path: Path) -> None:
    _build_role_corpus(tmp_path)
    corpus = load_corpus(tmp_path)

    a = score_claims(corpus, _target(), now="2025-06")
    b = score_claims(corpus, _target(), now="2025-06")
    assert {k: v.total for k, v in a.items()} == {k: v.total for k, v in b.items()}


# --- Signal: emphasis_skill_overlap --------------------------------------


def test_emphasis_skill_match_adds_positive_component(tmp_path: Path) -> None:
    _build_role_corpus(
        tmp_path,
        role_skill_ids=["python"],
        skills=[("python", None)],
    )
    corpus = load_corpus(tmp_path)
    scores = score_claims(
        corpus,
        _target(emphasis=["python"]),
        _ONLY_EMPHASIS,
        now="2025-01",
    )

    sb = scores["c"]
    assert sb.components == {"emphasis_skill_overlap": 3.0}
    assert sb.total == pytest.approx(3.0)


def test_emphasis_match_scales_with_count(tmp_path: Path) -> None:
    _build_role_corpus(
        tmp_path,
        role_skill_ids=["python", "rust", "go"],
        skills=[("python", None), ("rust", None), ("go", None)],
    )
    corpus = load_corpus(tmp_path)
    scores = score_claims(
        corpus,
        _target(emphasis=["python", "rust", "go"]),
        _ONLY_EMPHASIS,
        now="2025-01",
    )

    assert scores["c"].total == pytest.approx(9.0)


def test_emphasis_follows_skill_parent_chain(tmp_path: Path) -> None:
    """Target emphasizes 'python'; subject has 'django' with parent 'python'."""
    _build_role_corpus(
        tmp_path,
        role_skill_ids=["django"],
        skills=[("django", "python"), ("python", None)],
    )
    corpus = load_corpus(tmp_path)
    scores = score_claims(
        corpus,
        _target(emphasis=["python"]),
        _ONLY_EMPHASIS,
        now="2025-01",
    )

    assert scores["c"].components == {"emphasis_skill_overlap": 3.0}


def test_no_emphasis_match_contributes_nothing(tmp_path: Path) -> None:
    _build_role_corpus(
        tmp_path,
        role_skill_ids=["python"],
        skills=[("python", None)],
    )
    corpus = load_corpus(tmp_path)
    scores = score_claims(
        corpus,
        _target(emphasis=["rust"]),
        _ONLY_EMPHASIS,
        now="2025-01",
    )

    assert "emphasis_skill_overlap" not in scores["c"].components
    assert scores["c"].total == 0.0


# --- Signal: avoid_skill_overlap -----------------------------------------


def test_avoid_match_applies_penalty(tmp_path: Path) -> None:
    _build_role_corpus(
        tmp_path,
        role_skill_ids=["legacy_cobol"],
        skills=[("legacy_cobol", None)],
    )
    corpus = load_corpus(tmp_path)
    scores = score_claims(
        corpus,
        _target(avoid=["legacy_cobol"]),
        _ONLY_AVOID,
        now="2025-01",
    )

    assert scores["c"].components == {"avoid_skill_overlap": -5.0}


def test_avoid_beats_emphasis_at_single_match_each(tmp_path: Path) -> None:
    """Default weights: one avoid-match (-5) > one emphasis-match (+3)."""
    _build_role_corpus(
        tmp_path,
        role_skill_ids=["a", "b"],
        skills=[("a", None), ("b", None)],
    )
    corpus = load_corpus(tmp_path)
    scores = score_claims(
        corpus,
        _target(emphasis=["a"], avoid=["b"]),
        ScoringWeights(
            sourced=0.0,
            claim_type={},
            recency_weight=0.0,
        ),
        now="2025-01",
    )

    assert scores["c"].total == pytest.approx(-2.0)


# --- Signal: claim_type --------------------------------------------------


def test_claim_type_ordering_follows_defaults(tmp_path: Path) -> None:
    """impact > outcome > responsibility > quote > fact > context."""
    _minimal_person(tmp_path)
    _write(
        tmp_path / "organizations" / "o.yaml", "kind: organization\nid: o\nname: O\n"
    )
    _write(
        tmp_path / "roles" / "r.yaml",
        "kind: role\nid: r\ntitle: E\norganization_id: o\n"
        "period:\n  start: '2020-01'\n  end: '2024-12'\n",
    )
    for idx, ctype in enumerate(
        ["impact", "outcome", "quote", "responsibility", "fact", "context"]
    ):
        _write(
            tmp_path / "claims" / f"{ctype}.yaml",
            f"kind: claim\nid: {ctype}\nsubject_id: r\n"
            f"subject_kind: role\ntype: {ctype}\ntext: t{idx}\n",
        )

    corpus = load_corpus(tmp_path)
    scores = score_claims(corpus, _target(), _ONLY_CLAIM_TYPE, now="2025-01")

    totals = {cid: sb.total for cid, sb in scores.items()}
    assert totals["impact"] > totals["outcome"]
    assert totals["outcome"] > totals["responsibility"]
    assert totals["responsibility"] > totals["quote"]
    assert totals["quote"] > totals["fact"]
    assert totals["fact"] > totals["context"]

    for ctype, weight in DEFAULT_CLAIM_TYPE_WEIGHTS.items():
        assert totals[ctype] == pytest.approx(weight)


# --- Signal: sourced -----------------------------------------------------


def test_sourced_claim_gets_bonus_over_unsourced(tmp_path: Path) -> None:
    _minimal_person(tmp_path)
    _write(
        tmp_path / "organizations" / "o.yaml", "kind: organization\nid: o\nname: O\n"
    )
    _write(
        tmp_path / "roles" / "r.yaml",
        "kind: role\nid: r\ntitle: E\norganization_id: o\n"
        "period:\n  start: '2020-01'\n  end: '2024-12'\n",
    )
    _write(
        tmp_path / "source_docs" / "s.yaml",
        "kind: source_doc\nid: s\norigin: manual\nmime_type: text/plain\n"
        "sha256: '" + "0" * 64 + "'\n",
    )
    _write(
        tmp_path / "claims" / "sourced.yaml",
        "kind: claim\nid: sourced\nsubject_id: r\nsubject_kind: role\n"
        "text: s\nsources:\n  - s\n",
    )
    _write(
        tmp_path / "claims" / "bare.yaml",
        "kind: claim\nid: bare\nsubject_id: r\nsubject_kind: role\ntext: b\n",
    )

    corpus = load_corpus(tmp_path)
    scores = score_claims(corpus, _target(), _ONLY_SOURCED, now="2025-01")

    assert scores["sourced"].total == pytest.approx(0.5)
    assert scores["bare"].total == 0.0


# --- Signal: recency -----------------------------------------------------


def test_current_role_scores_higher_than_old_role(tmp_path: Path) -> None:
    _build_role_corpus(tmp_path, role_end="2015-01")
    old = load_corpus(tmp_path)
    old_score = score_claims(old, _target(), _ONLY_RECENCY, now="2025-01")["c"]

    tmp2 = tmp_path.parent / "recent"
    tmp2.mkdir()
    _build_role_corpus(tmp2, role_end="2024-12")
    recent = load_corpus(tmp2)
    recent_score = score_claims(recent, _target(), _ONLY_RECENCY, now="2025-01")["c"]

    assert recent_score.total > old_score.total


def test_ongoing_role_scores_as_fresh(tmp_path: Path) -> None:
    """An open-ended role should read as maximally recent."""
    _build_role_corpus(tmp_path, role_end=None)
    corpus = load_corpus(tmp_path)

    scores = score_claims(corpus, _target(), _ONLY_RECENCY, now="2025-06")

    assert scores["c"].components["recency"] == pytest.approx(1.0)


def test_recency_halflife_is_respected(tmp_path: Path) -> None:
    _build_role_corpus(tmp_path, role_end="2022-01")
    corpus = load_corpus(tmp_path)
    # 2022-01 to 2025-01 == 36 months == one half-life with default weights.
    scores = score_claims(corpus, _target(), _ONLY_RECENCY, now="2025-01")

    assert scores["c"].components["recency"] == pytest.approx(0.5)


def test_subject_without_date_has_no_recency_component(tmp_path: Path) -> None:
    """A testimonial has no date; the scorer should skip the recency signal
    rather than emit a zero or crash."""
    _minimal_person(tmp_path)
    _write(
        tmp_path / "testimonials" / "t.yaml",
        "kind: testimonial\nid: t\nquote: good work\nattribution: A\n",
    )
    _write(
        tmp_path / "claims" / "c.yaml",
        "kind: claim\nid: c\nsubject_id: t\nsubject_kind: testimonial\ntext: nice\n",
    )

    corpus = load_corpus(tmp_path)
    scores = score_claims(corpus, _target(), _ONLY_RECENCY, now="2025-01")

    assert "recency" not in scores["c"].components
    assert scores["c"].total == 0.0


# --- Weights behavior ----------------------------------------------------


def test_zero_weight_skips_component_entirely(tmp_path: Path) -> None:
    _build_role_corpus(
        tmp_path,
        role_skill_ids=["python"],
        skills=[("python", None)],
    )
    corpus = load_corpus(tmp_path)
    scores = score_claims(
        corpus,
        _target(emphasis=["python"]),
        ScoringWeights(
            emphasis_skill_overlap=0.0,
            avoid_skill_overlap=0.0,
            sourced=0.0,
            claim_type={},
            recency_weight=0.0,
        ),
        now="2025-01",
    )

    assert scores["c"].components == {}
    assert scores["c"].total == 0.0


def test_custom_claim_type_weights_override_defaults(tmp_path: Path) -> None:
    _build_role_corpus(tmp_path, claim_type="fact")
    corpus = load_corpus(tmp_path)
    scores = score_claims(
        corpus,
        _target(),
        ScoringWeights(
            emphasis_skill_overlap=0.0,
            avoid_skill_overlap=0.0,
            sourced=0.0,
            claim_type={"fact": 10.0},
            recency_weight=0.0,
        ),
        now="2025-01",
    )

    assert scores["c"].components == {"claim_type": 10.0}
