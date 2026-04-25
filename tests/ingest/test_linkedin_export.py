"""Tests for the expanded LinkedInExportIngester.

Each test builds a synthetic ZIP containing only the CSVs under test, so
the ingester's per-CSV behavior can be asserted in isolation. The
fixtures avoid any real personal data; sample names and quotes are
clearly fictional.
"""

from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

import pytest

from tool_cv_corpus.ingest.linkedin_export import LinkedInExportIngester
from tool_cv_corpus.schema import (
    Claim,
    Education,
    Organization,
    Person,
    Role,
    Skill,
    SourceDoc,
    Testimonial,
)

# ``conftest.py`` in this directory marks ``Testimonial.__test__ = False``
# so pytest does not try to collect the schema entity as a test class on
# import. See that file for rationale.


def _csv(rows: list[dict[str, str]], header: list[str]) -> bytes:
    """Render a list of dicts as a UTF-8 CSV blob (matches LinkedIn)."""
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=header)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buf.getvalue().encode("utf-8")


def _zip(path: Path, files: dict[str, bytes]) -> Path:
    """Build a ZIP at ``path`` whose root contains ``files``.

    Mirrors how LinkedIn ships the export: every CSV at the archive
    root, no enclosing folder.
    """
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return path


@pytest.fixture
def ingester() -> LinkedInExportIngester:
    return LinkedInExportIngester()


# --- accepts -----------------------------------------------------------


def test_accepts_export_zip(tmp_path: Path, ingester: LinkedInExportIngester) -> None:
    z = _zip(
        tmp_path / "ex.zip",
        {"Profile.csv": b"First Name,Last Name\nA,B\n"},
    )
    assert ingester.accepts(z) is True


def test_rejects_non_zip(tmp_path: Path, ingester: LinkedInExportIngester) -> None:
    p = tmp_path / "notes.txt"
    p.write_text("hello", encoding="utf-8")
    assert ingester.accepts(p) is False


def test_rejects_zip_without_known_csvs(
    tmp_path: Path, ingester: LinkedInExportIngester
) -> None:
    z = _zip(tmp_path / "irrelevant.zip", {"random.txt": b"nope"})
    assert ingester.accepts(z) is False


# --- source_doc --------------------------------------------------------


def test_source_doc_is_emitted_with_real_sha256(
    tmp_path: Path, ingester: LinkedInExportIngester
) -> None:
    z = _zip(
        tmp_path / "Complete_LinkedInDataExport_04-25-2026.zip",
        {
            "Profile.csv": _csv(
                [{"First Name": "X", "Last Name": "Y"}], ["First Name", "Last Name"]
            )
        },
    )
    out = ingester.ingest(z)
    assert len(out.sources) == 1
    src = out.sources[0]
    assert isinstance(src, SourceDoc)
    assert src.origin == "linkedin_export"
    assert src.mime_type == "application/zip"
    assert src.original_name == "Complete_LinkedInDataExport_04-25-2026.zip"
    assert src.captured_at == "2026-04-25"
    assert len(src.sha256) == 64
    # ID is deterministic from the digest, so re-running on the same ZIP
    # must produce the same source-doc identifier.
    second = ingester.ingest(z)
    assert second.sources[0].id == src.id


def test_source_doc_captured_at_falls_back_to_none_when_filename_unparseable(
    tmp_path: Path, ingester: LinkedInExportIngester
) -> None:
    z = _zip(
        tmp_path / "weird-name.zip",
        {"Profile.csv": _csv([{"First Name": "A"}], ["First Name"])},
    )
    out = ingester.ingest(z)
    assert out.sources[0].captured_at is None


# --- profile -----------------------------------------------------------


def test_profile_emits_person_and_summary_claim(
    tmp_path: Path, ingester: LinkedInExportIngester
) -> None:
    z = _zip(
        tmp_path / "ex.zip",
        {
            "Profile.csv": _csv(
                [
                    {
                        "First Name": "Test",
                        "Last Name": "User",
                        "Headline": "Senior Whatever",
                        "Summary": "Long-form profile summary text.",
                        "Geo Location": "Sacramento, California, United States",
                        "Twitter Handles": "",
                        "Websites": "https://example.com",
                    }
                ],
                [
                    "First Name",
                    "Last Name",
                    "Headline",
                    "Summary",
                    "Geo Location",
                    "Twitter Handles",
                    "Websites",
                ],
            )
        },
    )
    out = ingester.ingest(z)
    persons = [e for e in out.entities if isinstance(e, Person)]
    assert len(persons) == 1
    person = persons[0]
    assert person.id == "test_user"
    assert person.full_name == "Test User"
    assert person.headline == "Senior Whatever"
    assert person.location == "Sacramento, California, United States"
    assert person.contact == {"website": "https://example.com"}

    summary_claims = [
        c for c in out.claims if c.subject_kind == "person" and c.type == "context"
    ]
    assert len(summary_claims) == 1
    s = summary_claims[0]
    assert s.text == "Long-form profile summary text."
    assert s.subject_id == "test_user"
    assert s.sources == [out.sources[0].id]
    assert "linkedin" in s.tags and "profile_summary" in s.tags


def test_profile_with_no_summary_emits_person_only(
    tmp_path: Path, ingester: LinkedInExportIngester
) -> None:
    z = _zip(
        tmp_path / "ex.zip",
        {
            "Profile.csv": _csv(
                [{"First Name": "A", "Last Name": "B", "Summary": ""}],
                ["First Name", "Last Name", "Summary"],
            )
        },
    )
    out = ingester.ingest(z)
    assert any(isinstance(e, Person) for e in out.entities)
    assert not any(c.subject_kind == "person" for c in out.claims)


def test_profile_warns_on_extra_rows(
    tmp_path: Path, ingester: LinkedInExportIngester
) -> None:
    z = _zip(
        tmp_path / "ex.zip",
        {
            "Profile.csv": _csv(
                [
                    {"First Name": "A", "Last Name": "B"},
                    {"First Name": "C", "Last Name": "D"},
                ],
                ["First Name", "Last Name"],
            )
        },
    )
    out = ingester.ingest(z)
    persons = [e for e in out.entities if isinstance(e, Person)]
    assert len(persons) == 1
    assert persons[0].full_name == "A B"
    assert any("expected 1 row" in w for w in out.warnings)


# --- positions / description ------------------------------------------


def test_positions_emit_org_role_and_description_claim(
    tmp_path: Path, ingester: LinkedInExportIngester
) -> None:
    z = _zip(
        tmp_path / "ex.zip",
        {
            "Positions.csv": _csv(
                [
                    {
                        "Company Name": "ACME Corp",
                        "Title": "Storage Engineer",
                        "Description": "Ran storage for 700 servers.",
                        "Location": "Anywhere, CA",
                        "Started On": "May 2021",
                        "Finished On": "Dec 2021",
                    },
                    {
                        "Company Name": "ACME Corp",
                        "Title": "Junior Engineer",
                        "Description": "",
                        "Location": "",
                        "Started On": "Jan 2019",
                        "Finished On": "Apr 2021",
                    },
                ],
                [
                    "Company Name",
                    "Title",
                    "Description",
                    "Location",
                    "Started On",
                    "Finished On",
                ],
            )
        },
    )
    out = ingester.ingest(z)
    orgs = [e for e in out.entities if isinstance(e, Organization)]
    roles = [e for e in out.entities if isinstance(e, Role)]
    # Two positions, same org, dedup is a downstream merge concern; the
    # ingester emits one Organization per position row by design.
    assert len(orgs) == 2 and orgs[0].id == "acme_corp"
    assert len(roles) == 2

    desc_claims = [
        c for c in out.claims if c.subject_kind == "role" and c.type == "context"
    ]
    assert len(desc_claims) == 1
    d = desc_claims[0]
    assert d.text == "Ran storage for 700 servers."
    assert d.subject_id == "acme_corp_storage_engineer_2021"
    assert d.sources == [out.sources[0].id]
    assert "position_description" in d.tags


def test_positions_skip_rows_missing_required_fields(
    tmp_path: Path, ingester: LinkedInExportIngester
) -> None:
    z = _zip(
        tmp_path / "ex.zip",
        {
            "Positions.csv": _csv(
                [
                    {
                        "Company Name": "",
                        "Title": "Some Title",
                        "Started On": "May 2021",
                    }
                ],
                ["Company Name", "Title", "Started On"],
            )
        },
    )
    out = ingester.ingest(z)
    assert not any(isinstance(e, Role) for e in out.entities)
    assert any("missing company/title/start" in w for w in out.warnings)


# --- education / skills (unchanged behavior) --------------------------


def test_education_and_skills_round_trip(
    tmp_path: Path, ingester: LinkedInExportIngester
) -> None:
    z = _zip(
        tmp_path / "ex.zip",
        {
            "Education.csv": _csv(
                [
                    {
                        "School Name": "Cosumnes River College",
                        "Degree Name": "AA",
                        "Start Date": "1989",
                        "End Date": "1991",
                        "Notes": "General Studies",
                    }
                ],
                [
                    "School Name",
                    "Degree Name",
                    "Start Date",
                    "End Date",
                    "Notes",
                ],
            ),
            "Skills.csv": _csv(
                [{"Name": "SAN"}, {"Name": "Storage"}, {"Name": ""}],
                ["Name"],
            ),
        },
    )
    out = ingester.ingest(z)
    edus = [e for e in out.entities if isinstance(e, Education)]
    skills = [e for e in out.entities if isinstance(e, Skill)]
    assert len(edus) == 1 and edus[0].institution == "Cosumnes River College"
    assert {s.id for s in skills} == {"san", "storage"}


# --- recommendations ---------------------------------------------------


def test_recommendations_emit_testimonials_skipping_hidden(
    tmp_path: Path, ingester: LinkedInExportIngester
) -> None:
    z = _zip(
        tmp_path / "ex.zip",
        {
            "Recommendations_Received.csv": _csv(
                [
                    {
                        "First Name": "Pat",
                        "Last Name": "Reviewer",
                        "Company": "ACME",
                        "Job Title": "Manager",
                        "Text": "Pat said nice things.",
                        "Creation Date": "07/21/09, 12:11 PM",
                        "Status": "VISIBLE",
                    },
                    {
                        "First Name": "Hidden",
                        "Last Name": "Person",
                        "Company": "ACME",
                        "Job Title": "Director",
                        "Text": "This one is hidden.",
                        "Creation Date": "01/01/10, 09:00 AM",
                        "Status": "HIDDEN",
                    },
                    {
                        "First Name": "Old",
                        "Last Name": "Export",
                        "Company": "ACME",
                        "Job Title": "Lead",
                        "Text": "No status field set.",
                        "Creation Date": "02/02/11, 09:00 AM",
                        "Status": "",
                    },
                ],
                [
                    "First Name",
                    "Last Name",
                    "Company",
                    "Job Title",
                    "Text",
                    "Creation Date",
                    "Status",
                ],
            )
        },
    )
    out = ingester.ingest(z)
    ts = [e for e in out.entities if isinstance(e, Testimonial)]
    assert len(ts) == 2
    by_attr = {t.attribution: t for t in ts}
    assert "Pat Reviewer" in by_attr
    assert "Old Export" in by_attr
    assert "Hidden Person" not in by_attr
    assert by_attr["Pat Reviewer"].relationship == "Manager, ACME"
    assert by_attr["Pat Reviewer"].quote == "Pat said nice things."


def test_recommendations_dedupe_id_collisions(
    tmp_path: Path, ingester: LinkedInExportIngester
) -> None:
    """Two recs from the same person on the same date stay distinct."""
    rows = [
        {
            "First Name": "Same",
            "Last Name": "Person",
            "Company": "X",
            "Job Title": "Y",
            "Text": f"Quote {i}",
            "Creation Date": "07/21/09, 12:11 PM",
            "Status": "VISIBLE",
        }
        for i in range(3)
    ]
    z = _zip(
        tmp_path / "ex.zip",
        {
            "Recommendations_Received.csv": _csv(
                rows,
                [
                    "First Name",
                    "Last Name",
                    "Company",
                    "Job Title",
                    "Text",
                    "Creation Date",
                    "Status",
                ],
            )
        },
    )
    out = ingester.ingest(z)
    ts = [e for e in out.entities if isinstance(e, Testimonial)]
    ids = [t.id for t in ts]
    assert len(ids) == len(set(ids)) == 3


# --- endorsements ------------------------------------------------------


def test_endorsements_emit_claims_and_auto_add_missing_skills(
    tmp_path: Path, ingester: LinkedInExportIngester
) -> None:
    z = _zip(
        tmp_path / "ex.zip",
        {
            "Skills.csv": _csv([{"Name": "SAN"}], ["Name"]),
            "Endorsement_Received_Info.csv": _csv(
                [
                    {
                        "Endorsement Date": "2023/08/08 16:02:04 UTC",
                        "Skill Name": "SAN",
                        "Endorser First Name": "Stacey",
                        "Endorser Last Name": "Hale",
                        "Endorser Public Url": "https://example.com/stacey",
                        "Endorsement Status": "ACCEPTED",
                    },
                    {
                        "Endorsement Date": "2022/07/10 02:30:48 UTC",
                        "Skill Name": "Brand New Skill",
                        "Endorser First Name": "Jeff",
                        "Endorser Last Name": "Mayes",
                        "Endorser Public Url": "https://example.com/jeff",
                        "Endorsement Status": "ACCEPTED",
                    },
                    {
                        "Endorsement Date": "2020/01/01 00:00:00 UTC",
                        "Skill Name": "SAN",
                        "Endorser First Name": "Pending",
                        "Endorser Last Name": "Person",
                        "Endorser Public Url": "",
                        "Endorsement Status": "PENDING",
                    },
                ],
                [
                    "Endorsement Date",
                    "Skill Name",
                    "Endorser First Name",
                    "Endorser Last Name",
                    "Endorser Public Url",
                    "Endorsement Status",
                ],
            ),
        },
    )
    out = ingester.ingest(z)
    skills = {e.id: e for e in out.entities if isinstance(e, Skill)}
    # Skills.csv had only "SAN"; endorsements add "brand_new_skill".
    assert set(skills) == {"san", "brand_new_skill"}

    endorsements = [c for c in out.claims if "endorsement" in c.tags]
    # PENDING row dropped, two ACCEPTED rows kept.
    assert len(endorsements) == 2
    by_subject = {c.subject_id: c for c in endorsements}
    assert by_subject["san"].text == "Endorsed by Stacey Hale"
    assert by_subject["brand_new_skill"].text == "Endorsed by Jeff Mayes"
    assert by_subject["san"].sources == [out.sources[0].id]
    assert "date:2023-08-08" in by_subject["san"].tags


def test_endorsements_skip_rows_missing_endorser(
    tmp_path: Path, ingester: LinkedInExportIngester
) -> None:
    z = _zip(
        tmp_path / "ex.zip",
        {
            "Endorsement_Received_Info.csv": _csv(
                [
                    {
                        "Endorsement Date": "2023/08/08 16:02:04 UTC",
                        "Skill Name": "SAN",
                        "Endorser First Name": "",
                        "Endorser Last Name": "",
                        "Endorsement Status": "ACCEPTED",
                    }
                ],
                [
                    "Endorsement Date",
                    "Skill Name",
                    "Endorser First Name",
                    "Endorser Last Name",
                    "Endorsement Status",
                ],
            )
        },
    )
    out = ingester.ingest(z)
    assert not any("endorsement" in c.tags for c in out.claims)
    assert any("missing endorser name" in w for w in out.warnings)


def test_endorsement_claims_have_unique_ids_for_same_endorser_same_skill(
    tmp_path: Path, ingester: LinkedInExportIngester
) -> None:
    rows = [
        {
            "Endorsement Date": "2022/07/10 02:30:48 UTC",
            "Skill Name": "SAN",
            "Endorser First Name": "Jeff",
            "Endorser Last Name": "Mayes",
            "Endorser Public Url": "",
            "Endorsement Status": "ACCEPTED",
        }
        for _ in range(2)
    ]
    z = _zip(
        tmp_path / "ex.zip",
        {
            "Endorsement_Received_Info.csv": _csv(
                rows,
                [
                    "Endorsement Date",
                    "Skill Name",
                    "Endorser First Name",
                    "Endorser Last Name",
                    "Endorser Public Url",
                    "Endorsement Status",
                ],
            )
        },
    )
    out = ingester.ingest(z)
    endorsements = [c for c in out.claims if "endorsement" in c.tags]
    ids = [c.id for c in endorsements]
    assert len(ids) == len(set(ids)) == 2


# --- end-to-end --------------------------------------------------------


def test_end_to_end_full_export(
    tmp_path: Path, ingester: LinkedInExportIngester
) -> None:
    """One ZIP with every supported CSV; assert all surfaces fire and
    that every emitted Claim references the sole SourceDoc."""
    z = _zip(
        tmp_path / "Complete_LinkedInDataExport_04-25-2026.zip",
        {
            "Profile.csv": _csv(
                [
                    {
                        "First Name": "Test",
                        "Last Name": "User",
                        "Headline": "Storage Architect",
                        "Summary": "Years of storage work.",
                        "Geo Location": "Sacramento, CA, US",
                    }
                ],
                ["First Name", "Last Name", "Headline", "Summary", "Geo Location"],
            ),
            "Positions.csv": _csv(
                [
                    {
                        "Company Name": "ACME",
                        "Title": "Storage Engineer",
                        "Description": "Ran the storage tier.",
                        "Location": "CA",
                        "Started On": "Jan 2020",
                        "Finished On": "Dec 2022",
                    }
                ],
                [
                    "Company Name",
                    "Title",
                    "Description",
                    "Location",
                    "Started On",
                    "Finished On",
                ],
            ),
            "Education.csv": _csv(
                [
                    {
                        "School Name": "Some College",
                        "Degree Name": "AA",
                        "Start Date": "2010",
                        "End Date": "2012",
                    }
                ],
                ["School Name", "Degree Name", "Start Date", "End Date"],
            ),
            "Skills.csv": _csv([{"Name": "SAN"}], ["Name"]),
            "Recommendations_Received.csv": _csv(
                [
                    {
                        "First Name": "Pat",
                        "Last Name": "Reviewer",
                        "Company": "ACME",
                        "Job Title": "Manager",
                        "Text": "Pat said nice things.",
                        "Creation Date": "07/21/09, 12:11 PM",
                        "Status": "VISIBLE",
                    }
                ],
                [
                    "First Name",
                    "Last Name",
                    "Company",
                    "Job Title",
                    "Text",
                    "Creation Date",
                    "Status",
                ],
            ),
            "Endorsement_Received_Info.csv": _csv(
                [
                    {
                        "Endorsement Date": "2023/08/08 16:02:04 UTC",
                        "Skill Name": "SAN",
                        "Endorser First Name": "Stacey",
                        "Endorser Last Name": "Hale",
                        "Endorser Public Url": "",
                        "Endorsement Status": "ACCEPTED",
                    }
                ],
                [
                    "Endorsement Date",
                    "Skill Name",
                    "Endorser First Name",
                    "Endorser Last Name",
                    "Endorser Public Url",
                    "Endorsement Status",
                ],
            ),
        },
    )
    out = ingester.ingest(z)

    kinds = {type(e).__name__ for e in out.entities}
    assert {
        "Person",
        "Organization",
        "Role",
        "Education",
        "Skill",
        "Testimonial",
    } <= kinds

    assert len(out.sources) == 1
    src_id = out.sources[0].id
    # Every Claim that names a source names *this* source.
    sourced = [c for c in out.claims if c.sources]
    assert sourced, "expected at least one sourced claim"
    assert all(src_id in c.sources for c in sourced)

    # And every claim subject resolves to an entity we just emitted, so
    # validator check ``_c07`` would pass on this delta.
    keys = {(type(e).__name__.lower(), e.id) for e in out.entities}

    def _resolves(c: Claim) -> bool:
        return (c.subject_kind, c.subject_id) in keys

    assert all(_resolves(c) for c in out.claims)
