"""Tests for the schema-driven prompt engine.

The engine is exercised through ``ScriptedPrompter`` which replays a
queue of canned responses; each test pins both the *result* (what the
wizard built) and the *order* of prompts (by exhausting the queue
exactly).

Walk order for entity models (subclasses of ``Entity``):

    {subclass-specific fields, in declaration order}
    visibility
    tags
    id  (asked separately at the end of prompt_for_entity)

The wizard skips ``kind`` (discriminator) and ``schema_version``
unconditionally. ``id`` is also skipped during the field walk and
handled by ``prompt_for_entity`` at the end so the suggested slug can
be built from the values the user just typed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tool_cv_corpus.author.prompts import (
    ScriptedPrompter,
    prompt_for_claim,
    prompt_for_entity,
)
from tool_cv_corpus.author.state import CorpusState, load_state
from tool_cv_corpus.author.writers import write_entity
from tool_cv_corpus.schema import (
    Achievement,
    Organization,
    Person,
    Role,
    Skill,
)


def _empty_state(tmp_path: Path) -> CorpusState:
    return load_state(tmp_path)


# --- person ---------------------------------------------------------


def test_person_minimal(tmp_path: Path) -> None:
    """Required fields only; every optional gets blank input."""
    p = ScriptedPrompter(
        [
            "Anthony Riles",  # full_name
            "",  # preferred_name (optional)
            "Consultant",  # headline (optional)
            "",  # pronouns (optional)
            "Sacramento, CA",  # location (optional)
            "",  # contact dict: blank key -> finish
            "public",  # visibility (Literal, default public)
            "",  # tags list: blank -> finish
            "",  # id: accept default suggestion (anthony_riles)
        ]
    )
    person = prompt_for_entity(Person, prompter=p, state=_empty_state(tmp_path))
    assert isinstance(person, Person)
    assert person.full_name == "Anthony Riles"
    assert person.headline == "Consultant"
    assert person.location == "Sacramento, CA"
    assert person.id == "anthony_riles"
    assert person.contact == {}
    assert p.remaining == 0


def test_person_with_contact_dict(tmp_path: Path) -> None:
    """``contact`` is a ``dict[str, str]``; key/value pairs until blank key."""
    p = ScriptedPrompter(
        [
            "Anthony Riles",
            "",
            "",
            "",
            "",
            # contact dict iteration:
            "email",  # key
            "anthony@example.com",  # value
            "github",  # key
            "https://github.com/example",  # value
            "",  # blank key -> finish
            "public",  # visibility
            "",  # tags
            "anthony",  # id override
        ]
    )
    person = prompt_for_entity(Person, prompter=p, state=_empty_state(tmp_path))
    assert person.contact == {
        "email": "anthony@example.com",
        "github": "https://github.com/example",
    }
    assert person.id == "anthony"


# --- skill (Literal enums + optional float) -------------------------


def test_skill_with_literal_and_optional_float(tmp_path: Path) -> None:
    p = ScriptedPrompter(
        [
            "Python",  # name
            "foundational",  # tier (Literal)
            "expert",  # confidence (Literal)
            "8",  # years (optional float)
            "",  # last_used (optional)
            # aliases list[str]:
            "py",
            "python3",
            "",  # blank -> finish
            "",  # parent_id (FK picker, allow_none) -> skip
            "public",  # visibility
            "",  # tags
            "",  # id default
        ]
    )
    skill = prompt_for_entity(Skill, prompter=p, state=_empty_state(tmp_path))
    assert skill.name == "Python"
    assert skill.tier == "foundational"
    assert skill.confidence == "expert"
    assert skill.years == 8.0
    assert skill.aliases == ["py", "python3"]
    assert skill.parent_id is None
    assert p.remaining == 0


def test_skill_invalid_float_re_prompts(tmp_path: Path) -> None:
    """Bad numeric input is caught locally and the same field is re-asked."""
    p = ScriptedPrompter(
        [
            "Python",  # name
            "applied",  # tier
            "working",  # confidence
            "lots",  # years -> ValueError, retry
            "8",  # years retry
            "",  # last_used
            "",  # aliases blank
            "",  # parent_id
            "public",  # visibility
            "",  # tags
            "",  # id
        ]
    )
    skill = prompt_for_entity(Skill, prompter=p, state=_empty_state(tmp_path))
    assert skill.years == 8.0
    assert any("expected float" in m for kind, m in p.log if kind == "error")
    assert p.remaining == 0


# --- foreign-key picker --------------------------------------------


def test_role_picks_existing_organization(tmp_path: Path) -> None:
    """``Role.organization_id`` lists existing orgs from CorpusState."""
    write_entity(tmp_path, Organization(id="acme", name="ACME"))
    write_entity(tmp_path, Organization(id="globex", name="Globex"))
    state = load_state(tmp_path)

    p = ScriptedPrompter(
        [
            "Storage Engineer",  # title
            "globex",  # organization_id (FK pick by id)
            "full_time",  # employment_type
            # period (DateRange nested):
            "2021-03",  # start
            "",  # end (optional)
            "Remote",  # location
            False,  # remote (bool)
            "",  # headline
            # project_ids list[str] FK:
            "",  # blank -> finish
            "",  # achievement_ids: blank
            "",  # skill_ids: blank
            "public",  # visibility
            "",  # tags
            "",  # id default (globex_storage_engineer_2021)
        ]
    )
    role = prompt_for_entity(Role, prompter=p, state=state)
    assert role.organization_id == "globex"
    assert role.period.start == "2021-03"
    assert role.id == "globex_storage_engineer_2021"
    assert p.remaining == 0


def test_role_freeform_fk_value_accepted(tmp_path: Path) -> None:
    """A user can name an organization that does not exist yet.

    The validator's ``_c05_foreign_keys`` check is the right gate for
    dangling references; the wizard must not block the user from
    declaring a Role before the Organization is on disk.
    """
    state = load_state(tmp_path)
    p = ScriptedPrompter(
        [
            "Storage Engineer",
            "future_employer",  # FK with no existing match -> freeform
            "full_time",
            "2021-03",
            "",
            "",
            False,
            "",
            "",
            "",
            "",
            "public",
            "",
            "",
        ]
    )
    role = prompt_for_entity(Role, prompter=p, state=state)
    assert role.organization_id == "future_employer"


# --- list of nested models -----------------------------------------


def test_achievement_with_two_metrics(tmp_path: Path) -> None:
    """``metrics: list[ImpactMetric]`` recurses into the nested model."""
    p = ScriptedPrompter(
        [
            "Cut backup window from 14h to 6h",  # headline
            "",  # role_id (FK optional) -> skip
            "",  # project_id optional FK
            "2022-09",  # date optional
            # metrics list, two entries:
            True,  # add another ImpactMetric? yes
            # ImpactMetric fields, declaration order:
            "Backup window",  # name
            "6.0",  # value (optional float)
            "h",  # unit (optional str)
            "",  # delta_pct (optional float)
            "14.0",  # baseline (optional float)
            "decrease",  # direction (Literal optional)
            "Q3 2022",  # timeframe (optional str)
            True,  # add another?
            "Failed backups per week",
            "0",
            "errors",
            "100",
            "5",
            "decrease",
            "Q3 2022",
            False,  # no more metrics
            # skill_ids list[str] FK:
            "",  # blank
            "public",  # visibility
            "",  # tags
            "",  # id default
        ]
    )
    ach = prompt_for_entity(Achievement, prompter=p, state=_empty_state(tmp_path))
    assert ach.headline.startswith("Cut backup window")
    assert len(ach.metrics) == 2
    assert ach.metrics[0].name == "Backup window"
    assert ach.metrics[0].direction == "decrease"
    assert ach.metrics[1].delta_pct == 100.0
    assert p.remaining == 0


# --- claim ---------------------------------------------------------


def test_claim_with_prefilled_subject(tmp_path: Path) -> None:
    """Subject kind/id passed in are not re-asked at the menu, but are
    still walked in the model dict (then overwritten by the prefill)."""
    write_entity(tmp_path, Person(id="anthony", full_name="Anthony Riles"))
    state = load_state(tmp_path)
    # Claim model walk order (id is skipped, subject_id and subject_kind
    # are prompted but later overwritten by the prefill arguments):
    #   subject_id, subject_kind, type, text, sources, superseded_by,
    #   visibility (LATE), tags (LATE)
    p = ScriptedPrompter(
        [
            "anthony",  # subject_id (will be overwritten)
            "person",  # subject_kind (will be overwritten)
            "context",  # type (Literal)
            "Long-form context paragraph.",  # text
            "",  # sources list blank -> finish
            "",  # superseded_by optional
            "public",  # visibility
            "linkedin",  # tags entry
            "",  # tags blank to finish
        ]
    )
    claim = prompt_for_claim(
        prompter=p, state=state, subject_kind="person", subject_id="anthony"
    )
    assert claim.subject_id == "anthony"
    assert claim.subject_kind == "person"
    assert claim.type == "context"
    assert claim.text == "Long-form context paragraph."
    assert claim.tags == ["linkedin"]
    assert p.remaining == 0


def test_claim_prompts_for_subject_when_not_prefilled(tmp_path: Path) -> None:
    write_entity(tmp_path, Person(id="anthony", full_name="Anthony Riles"))
    state = load_state(tmp_path)
    p = ScriptedPrompter(
        [
            "person",  # subject kind menu choice
            "anthony",  # subject FK choice
            # Claim model walk:
            "anthony",  # subject_id (overwritten)
            "person",  # subject_kind (overwritten)
            "fact",  # type
            "He prefers direct prose.",  # text
            "",  # sources blank
            "",  # superseded_by
            "public",  # visibility
            "",  # tags
        ]
    )
    claim = prompt_for_claim(prompter=p, state=state)
    assert claim.subject_kind == "person"
    assert claim.subject_id == "anthony"
    # ID was auto-suggested because none was set during the walk.
    assert claim.id.startswith("anthony")


def test_claim_on_empty_corpus_errors(tmp_path: Path) -> None:
    state = load_state(tmp_path)  # empty
    p = ScriptedPrompter([])
    with pytest.raises(RuntimeError, match="empty corpus"):
        prompt_for_claim(prompter=p, state=state)


# --- end-to-end: build, write, validate ----------------------------


def test_authored_entities_pass_validate(tmp_path: Path) -> None:
    """Walk the wizard for several kinds, write to disk, run the validator.

    This is the integration anchor: if anything in the prompt -> build
    -> write chain produces a YAML file that ``cv-corpus validate``
    rejects, this test catches it before a user does.
    """
    from tool_cv_corpus.validate.runner import ValidatorRunner

    # Person:
    p1 = ScriptedPrompter(
        [
            "Anthony Riles",
            "",
            "Consultant",
            "",
            "Sacramento, CA",
            "",  # contact blank
            "public",
            "",  # tags
            "",  # id default
        ]
    )
    person = prompt_for_entity(Person, prompter=p1, state=load_state(tmp_path))
    write_entity(tmp_path, person)

    # Organization:
    p2 = ScriptedPrompter(
        [
            "ACME",  # name
            "",  # website
            "",  # industry
            "",  # size
            "",  # description
            "public",
            "",
            "",
        ]
    )
    org = prompt_for_entity(Organization, prompter=p2, state=load_state(tmp_path))
    write_entity(tmp_path, org)

    # Role with FK to existing org:
    p3 = ScriptedPrompter(
        [
            "Storage Engineer",
            "acme",  # FK pick
            "full_time",
            "2021-03",
            "",
            "Remote",
            False,
            "",
            "",
            "",
            "",
            "public",
            "",
            "",
        ]
    )
    role = prompt_for_entity(Role, prompter=p3, state=load_state(tmp_path))
    write_entity(tmp_path, role)

    report = ValidatorRunner(tmp_path).run()
    errors = [c for c in report.checks if c.status == "error"]
    assert errors == [], f"validator errors: {errors}"
