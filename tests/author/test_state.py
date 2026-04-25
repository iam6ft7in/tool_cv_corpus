"""Tests for ``CorpusState``: existing-entity discovery for FK pickers."""

from __future__ import annotations

from pathlib import Path

import yaml

from tool_cv_corpus.author.state import load_state


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def test_load_state_indexes_each_kind(tmp_path: Path) -> None:
    _write(
        tmp_path / "persons" / "anthony.yaml",
        {"kind": "person", "id": "anthony", "full_name": "Anthony Riles"},
    )
    _write(
        tmp_path / "organizations" / "acme.yaml",
        {"kind": "organization", "id": "acme", "name": "ACME"},
    )
    _write(
        tmp_path / "skills" / "san.yaml",
        {"kind": "skill", "id": "san", "name": "SAN", "tier": "applied"},
    )

    state = load_state(tmp_path)
    assert state.has("person", "anthony")
    assert state.has("organization", "acme")
    assert state.has("skill", "san")
    assert not state.has("skill", "missing")
    assert {e.id for e in state.list_kind("skill")} == {"san"}


def test_load_state_skips_claims_and_unknown_kinds(tmp_path: Path) -> None:
    _write(
        tmp_path / "claims" / "c1.yaml",
        {
            "kind": "claim",
            "id": "c1",
            "subject_id": "anthony",
            "subject_kind": "person",
            "text": "ignored at load_state time",
        },
    )
    _write(
        tmp_path / "stuff" / "weird.yaml",
        {"kind": "not_a_kind", "id": "x"},
    )
    state = load_state(tmp_path)
    # Claims are intentionally skipped for the wizard's FK pickers.
    assert "claim" not in state.by_kind
    # Unknown kinds drop through with a warning rather than raising.
    assert any("schema error" in w for w in state.warnings)


def test_load_state_collects_parse_warnings(tmp_path: Path) -> None:
    bad = tmp_path / "persons" / "broken.yaml"
    bad.parent.mkdir(parents=True)
    bad.write_text("kind: person\nid: x\nfull_name: [unclosed", encoding="utf-8")
    state = load_state(tmp_path)
    assert state.warnings
