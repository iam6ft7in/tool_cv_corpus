"""Tests for the on-disk writers and ID suggester.

These cover the deterministic surface (no prompts), so they pin the
filename / directory / ID conventions that the prompt engine and CLI
rely on.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tool_cv_corpus.author.writers import (
    DIRECTORY_BY_KIND,
    slug,
    suggest_entity_id,
    write_claim,
    write_entity,
)
from tool_cv_corpus.schema import (
    Achievement,
    Claim,
    Organization,
    Person,
    Role,
    Skill,
)


def test_directory_by_kind_covers_every_entity_kind() -> None:
    """Adding a new entity kind must register a directory.

    The CLI iterates ``DIRECTORY_BY_KIND`` to scaffold subdirs; missing
    entries would silently break ``cv-corpus author --kind <new_kind>``.
    """
    expected = {
        "person",
        "organization",
        "role",
        "project",
        "achievement",
        "skill",
        "education",
        "publication",
        "artifact",
        "testimonial",
        "cover_letter_seed",
        "target",
        "source_doc",
    }
    assert expected <= set(DIRECTORY_BY_KIND)


def test_slug_basic_and_empty() -> None:
    assert slug("Anthony Riles") == "anthony_riles"
    assert slug("  hello, world!  ") == "hello_world"
    assert slug("") == "item"
    assert slug("---") == "item"


def test_suggest_id_uses_recipe_fields() -> None:
    sid = suggest_entity_id(
        "person", {"full_name": "Anthony Riles"}, existing_ids=set()
    )
    assert sid == "anthony_riles"

    rid = suggest_entity_id(
        "role",
        {
            "title": "Storage Engineer",
            "organization_id": "acme_corp",
            "period": {"start": "2021-03"},
        },
        existing_ids=set(),
    )
    # Role recipe is (organization_id, title), then start year appended.
    assert rid == "acme_corp_storage_engineer_2021"


def test_suggest_id_falls_back_to_kind_when_no_field_matches() -> None:
    sid = suggest_entity_id("achievement", {}, existing_ids=set())
    assert sid == "achievement"


def test_suggest_id_collision_appends_counter() -> None:
    sid = suggest_entity_id(
        "skill",
        {"name": "Python"},
        existing_ids={"python", "python_2"},
    )
    assert sid == "python_3"


def test_write_entity_writes_yaml_with_kind_first(tmp_path: Path) -> None:
    person = Person(
        id="anthony_riles", full_name="Anthony Riles", headline="Consultant"
    )
    target = write_entity(tmp_path, person)
    assert target == tmp_path / "persons" / "anthony_riles.yaml"
    data = yaml.safe_load(target.read_text(encoding="utf-8"))
    # Discriminator is first key on disk.
    assert next(iter(data)) == "kind"
    assert data["kind"] == "person"
    assert data["full_name"] == "Anthony Riles"


def test_write_entity_refuses_to_overwrite(tmp_path: Path) -> None:
    org = Organization(id="acme", name="ACME")
    write_entity(tmp_path, org)
    with pytest.raises(FileExistsError):
        write_entity(tmp_path, org)


def test_write_claim_attaches_kind_discriminator(tmp_path: Path) -> None:
    claim = Claim(
        id="acme_role_responsibility",
        subject_id="acme_role",
        subject_kind="role",
        type="responsibility",
        text="Owned the backup tier.",
    )
    target = write_claim(tmp_path, claim)
    assert target == tmp_path / "claims" / "acme_role_responsibility.yaml"
    data = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert data["kind"] == "claim"
    assert data["subject_id"] == "acme_role"


def test_round_trip_for_every_kind(tmp_path: Path) -> None:
    """Every entity we know how to write must read back as the same model.

    Catches discriminator/serialisation drift: if an entity's on-disk
    keys don't match its model, a future ``cv-corpus validate`` over a
    freshly authored corpus would fail.
    """
    samples = [
        Person(id="p", full_name="Test User"),
        Organization(id="o", name="ACME"),
        Role(
            id="r",
            title="Engineer",
            organization_id="o",
            period={"start": "2020-01"},
        ),
        Skill(id="s", name="Python", tier="foundational"),
        Achievement(id="a", headline="Shipped a thing"),
    ]
    written: list[tuple[Path, str]] = []
    for entity in samples:
        path = write_entity(tmp_path, entity)
        written.append((path, entity.kind))

    for path, kind in written:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert data["kind"] == kind
