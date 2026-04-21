"""Schema round-trip and validation tests.

Round-trip coverage is the main guarantee: a YAML-shaped dict validates
into an entity and ``model_dump()`` returns an equivalent dict. If this
breaks, on-disk corpora stop loading silently, which is exactly the failure
mode the schema is designed to prevent.
"""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from tool_cv_corpus.schema import (
    SCHEMA_VERSION,
    Achievement,
    AnyEntity,
    Claim,
    DateRange,
    ImpactMetric,
    Organization,
    Person,
    Role,
    Skill,
    SourceDoc,
    Target,
)


def test_partial_date_accepts_year_only() -> None:
    dr = DateRange(start="2021")
    assert dr.start == "2021"
    assert dr.end is None


def test_partial_date_accepts_year_month_and_full() -> None:
    DateRange(start="2021-03", end="2023-11-15")


@pytest.mark.parametrize(
    "bad",
    [
        "21",  # too short
        "2021-13",  # bad month
        "2021-00",
        "2021-02-30",  # bad day
        "2021/03",  # wrong separator
        "March 2021",
        "",
    ],
)
def test_partial_date_rejects_malformed(bad: str) -> None:
    with pytest.raises(ValidationError):
        DateRange(start=bad)


def test_date_range_end_before_start_rejected() -> None:
    with pytest.raises(ValidationError):
        DateRange(start="2022-06", end="2022-05")


def test_date_range_end_after_start_mixed_granularity_ok() -> None:
    DateRange(start="2021-03", end="2023")


def test_entity_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        Person(
            id="me",
            full_name="Jordan Taylor",
            what_is_this="nope",  # type: ignore[call-arg]
        )


def test_role_round_trip() -> None:
    data = {
        "kind": "role",
        "id": "senior_swe_acme",
        "title": "Senior Software Engineer",
        "organization_id": "acme",
        "employment_type": "full_time",
        "period": {"start": "2021-03", "end": "2023-11"},
        "location": "Remote",
        "remote": True,
        "achievement_ids": ["ach_launched_billing"],
        "skill_ids": ["python", "postgres"],
    }
    role = Role.model_validate(data)
    dumped = role.model_dump(exclude_defaults=True)
    re_role = Role.model_validate(dumped)
    assert re_role == role
    assert role.schema_version == SCHEMA_VERSION


def test_achievement_with_metrics_round_trip() -> None:
    ach = Achievement(
        id="ach_launched_billing",
        headline="Launched metered billing for 2.1k customers",
        role_id="senior_swe_acme",
        date="2022-09",
        metrics=[
            ImpactMetric(
                name="ARR",
                delta_pct=18.0,
                direction="increase",
                timeframe="Q4 2022",
            ),
        ],
    )
    again = Achievement.model_validate(ach.model_dump())
    assert again == ach


def test_skill_requires_tier() -> None:
    with pytest.raises(ValidationError):
        Skill(id="python", name="Python")  # type: ignore[call-arg]


def test_skill_tier_validated() -> None:
    with pytest.raises(ValidationError):
        Skill(id="python", name="Python", tier="foundation")  # type: ignore[arg-type]
    Skill(id="python", name="Python", tier="foundational")


def test_source_doc_sha256_pattern() -> None:
    good = "a" * 64
    SourceDoc(id="sd1", sha256=good, mime_type="application/pdf")
    with pytest.raises(ValidationError):
        SourceDoc(id="sd2", sha256="z" * 64, mime_type="application/pdf")
    with pytest.raises(ValidationError):
        SourceDoc(id="sd3", sha256="a" * 63, mime_type="application/pdf")


def test_claim_requires_subject_and_text() -> None:
    with pytest.raises(ValidationError):
        Claim(
            id="c1",
            subject_id="",
            subject_kind="role",
            text="",
        )
    Claim(
        id="c1",
        subject_id="senior_swe_acme",
        subject_kind="role",
        text="Owned end-to-end billing roadmap.",
    )


def test_organization_and_target_roundtrip() -> None:
    org = Organization(id="acme", name="ACME Corp", industry="B2B SaaS")
    tgt = Target(
        id="tgt_principal_eng_foo",
        role_title="Principal Engineer",
        organization_name="Foo Technologies",
        requirements=["10+ years", "Python"],
        emphasis_skill_ids=["python", "distributed_systems"],
    )
    for obj in (org, tgt):
        again = type(obj).model_validate(obj.model_dump())
        assert again == obj


def test_discriminated_union_dispatches_by_kind() -> None:
    adapter: TypeAdapter[AnyEntity] = TypeAdapter(AnyEntity)
    data = {
        "kind": "organization",
        "id": "acme",
        "name": "ACME Corp",
    }
    parsed = adapter.validate_python(data)
    assert isinstance(parsed, Organization)
    assert parsed.name == "ACME Corp"
