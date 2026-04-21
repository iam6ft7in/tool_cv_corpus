"""Tests for the v0.2 corpus loader.

The example corpus lives at ``examples/corpus_jordan_taylor`` and is also
used by the ``validate`` pre-commit hook, so we have a strong guarantee
that it conforms to the 11-check validator. These tests therefore pin
loader behavior that goes *beyond* validation: visibility filtering,
supersession resolution, and the immutable ``Corpus`` contract.
"""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

import pytest

from tool_cv_corpus.generate.loader import (
    Corpus,
    CorpusLoadError,
    load_corpus,
)
from tool_cv_corpus.schema.entities import Person, Role, Skill

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EXAMPLE = REPO_ROOT / "examples" / "corpus_jordan_taylor"


def test_load_example_corpus_returns_corpus() -> None:
    corpus = load_corpus(EXAMPLE)

    assert isinstance(corpus, Corpus)
    assert corpus.root == EXAMPLE
    assert corpus.max_visibility == "private"
    assert isinstance(corpus.person, Person)
    assert corpus.person.id == "jordan_taylor"
    assert corpus.person.full_name == "Jordan Taylor"
    assert ("person", "jordan_taylor") in corpus.entities


def test_entities_map_is_read_only() -> None:
    corpus = load_corpus(EXAMPLE)
    assert isinstance(corpus.entities, MappingProxyType)
    with pytest.raises(TypeError):
        corpus.entities[("person", "x")] = corpus.person  # type: ignore[index]


def test_claim_lists_are_tuples() -> None:
    corpus = load_corpus(EXAMPLE)
    for claims in corpus.claims_by_subject.values():
        assert isinstance(claims, tuple)


def test_skills_by_id_indexes_all_skills() -> None:
    corpus = load_corpus(EXAMPLE)

    direct = {k[1] for k in corpus.entities if k[0] == "skill"}
    assert set(corpus.skills_by_id.keys()) == direct
    assert all(isinstance(v, Skill) for v in corpus.skills_by_id.values())


def test_roles_chronological_is_newest_first() -> None:
    corpus = load_corpus(EXAMPLE)

    roles = corpus.roles_chronological()
    assert len(roles) >= 1
    assert all(isinstance(r, Role) for r in roles)

    starts = [r.period.start for r in roles]
    assert starts == sorted(starts, reverse=True)


def test_claims_for_absent_subject_returns_empty_tuple() -> None:
    corpus = load_corpus(EXAMPLE)
    assert corpus.claims_for("role", "does_not_exist") == ()


def test_non_directory_raises() -> None:
    with pytest.raises(CorpusLoadError, match="not a directory"):
        load_corpus(REPO_ROOT / "README.md")


def _write_min_person(root: Path) -> None:
    (root / "persons").mkdir(parents=True, exist_ok=True)
    (root / "persons" / "p.yaml").write_text(
        "kind: person\nid: p\nfull_name: Pat\n",
        encoding="utf-8",
    )


def test_parse_error_names_the_file(tmp_path: Path) -> None:
    _write_min_person(tmp_path)
    bad = tmp_path / "broken.yaml"
    bad.write_text("foo: [unterminated", encoding="utf-8")

    with pytest.raises(CorpusLoadError) as exc_info:
        load_corpus(tmp_path)
    assert "broken.yaml" in str(exc_info.value)


def test_non_mapping_yaml_raises(tmp_path: Path) -> None:
    _write_min_person(tmp_path)
    (tmp_path / "list.yaml").write_text("- just\n- a\n- list\n", encoding="utf-8")

    with pytest.raises(CorpusLoadError, match="must be a mapping"):
        load_corpus(tmp_path)


def test_schema_failure_names_the_field(tmp_path: Path) -> None:
    _write_min_person(tmp_path)
    (tmp_path / "skills").mkdir()
    (tmp_path / "skills" / "s.yaml").write_text(
        "kind: skill\nid: s\nname: S\ntier: not_a_real_tier\n",
        encoding="utf-8",
    )

    with pytest.raises(CorpusLoadError, match="schema validation failed"):
        load_corpus(tmp_path)


def test_missing_person_raises(tmp_path: Path) -> None:
    (tmp_path / "skills").mkdir()
    (tmp_path / "skills" / "s.yaml").write_text(
        "kind: skill\nid: s\nname: S\ntier: applied\n",
        encoding="utf-8",
    )
    with pytest.raises(CorpusLoadError, match="no Person entity"):
        load_corpus(tmp_path)


def test_multiple_persons_raises(tmp_path: Path) -> None:
    (tmp_path / "persons").mkdir()
    (tmp_path / "persons" / "a.yaml").write_text(
        "kind: person\nid: a\nfull_name: A\n", encoding="utf-8"
    )
    (tmp_path / "persons" / "b.yaml").write_text(
        "kind: person\nid: b\nfull_name: B\n", encoding="utf-8"
    )
    with pytest.raises(CorpusLoadError, match="2 Person entities"):
        load_corpus(tmp_path)


def test_visibility_cap_drops_private_entities(tmp_path: Path) -> None:
    _write_min_person(tmp_path)
    (tmp_path / "skills").mkdir()
    (tmp_path / "skills" / "secret.yaml").write_text(
        "kind: skill\nid: secret\nname: Secret\ntier: applied\nvisibility: private\n",
        encoding="utf-8",
    )
    (tmp_path / "skills" / "public.yaml").write_text(
        "kind: skill\nid: pub\nname: Pub\ntier: applied\nvisibility: public\n",
        encoding="utf-8",
    )

    full = load_corpus(tmp_path, max_visibility="private")
    assert ("skill", "secret") in full.entities
    assert ("skill", "pub") in full.entities

    public = load_corpus(tmp_path, max_visibility="public")
    assert ("skill", "secret") not in public.entities
    assert ("skill", "pub") in public.entities

    nda = load_corpus(tmp_path, max_visibility="nda")
    assert ("skill", "secret") not in nda.entities
    assert ("skill", "pub") in nda.entities


def _write_role_with_claims(
    root: Path,
    claims: list[tuple[str, str | None, str]],
) -> None:
    """Helper: write a minimal org+role and one claim per tuple.

    Each tuple is ``(claim_id, superseded_by, visibility)``.
    """
    _write_min_person(root)
    (root / "organizations").mkdir()
    (root / "organizations" / "o.yaml").write_text(
        "kind: organization\nid: o\nname: O\n",
        encoding="utf-8",
    )
    (root / "roles").mkdir()
    (root / "roles" / "r.yaml").write_text(
        "kind: role\nid: r\ntitle: Engineer\norganization_id: o\n"
        "period:\n  start: '2020-01'\n  end: '2024-12'\n",
        encoding="utf-8",
    )
    (root / "claims").mkdir()
    for cid, superseded_by, vis in claims:
        sb_line = f"superseded_by: {superseded_by}\n" if superseded_by else ""
        (root / "claims" / f"{cid}.yaml").write_text(
            f"kind: claim\nid: {cid}\nsubject_id: r\n"
            f"subject_kind: role\ntext: {cid} text\n"
            f"visibility: {vis}\n{sb_line}",
            encoding="utf-8",
        )


def test_superseded_claim_is_dropped(tmp_path: Path) -> None:
    _write_role_with_claims(
        tmp_path,
        [("old", "new", "public"), ("new", None, "public")],
    )
    corpus = load_corpus(tmp_path)

    ids = {c.id for c in corpus.claims_for("role", "r")}
    assert ids == {"new"}


def test_broken_supersede_chain_keeps_claim(tmp_path: Path) -> None:
    _write_role_with_claims(
        tmp_path,
        [("old", "missing_successor", "public")],
    )
    corpus = load_corpus(tmp_path)

    ids = {c.id for c in corpus.claims_for("role", "r")}
    assert ids == {"old"}


def test_superseded_by_redacted_successor_keeps_claim(tmp_path: Path) -> None:
    """If the successor is redacted out, the predecessor survives.

    This preserves the user's best-available evidence when a newer claim
    lives behind an NDA and the render is public.
    """
    _write_role_with_claims(
        tmp_path,
        [("old", "new", "public"), ("new", None, "private")],
    )
    corpus = load_corpus(tmp_path, max_visibility="public")

    ids = {c.id for c in corpus.claims_for("role", "r")}
    assert ids == {"old"}


def test_claim_with_redacted_subject_is_dropped(tmp_path: Path) -> None:
    _write_min_person(tmp_path)
    (tmp_path / "skills").mkdir()
    (tmp_path / "skills" / "secret.yaml").write_text(
        "kind: skill\nid: secret\nname: Secret\ntier: applied\nvisibility: private\n",
        encoding="utf-8",
    )
    (tmp_path / "claims").mkdir()
    (tmp_path / "claims" / "c.yaml").write_text(
        "kind: claim\nid: c\nsubject_id: secret\n"
        "subject_kind: skill\ntext: about a secret skill\n"
        "visibility: public\n",
        encoding="utf-8",
    )

    public = load_corpus(tmp_path, max_visibility="public")
    assert public.claims_for("skill", "secret") == ()
    private = load_corpus(tmp_path, max_visibility="private")
    assert len(private.claims_for("skill", "secret")) == 1
