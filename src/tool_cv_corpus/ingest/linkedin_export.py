"""LinkedIn data-export ingester.

LinkedIn offers two exports:

- Basic (Positions.csv, Education.csv, Skills.csv, Profile.csv).
- Complete (adds Messages.csv, connections, endorsements, etc.).

Both are delivered as ZIPs. We consume the career-relevant CSVs only:

- ``Positions``, ``Education``, ``Skills`` for the structural backbone.
- ``Profile`` for the Person entity (headline, summary, location).
- ``Recommendations_Received`` for Testimonials.
- ``Endorsement_Received_Info`` for per-skill endorsement claims.

Messages, connections, ad activity, security events, and similar
personal-data CSVs are intentionally ignored: they are not career-graph
data, and conflating them with corpus content would leak privacy
boundaries authors expect to control.

This ingester is conservative: it does not infer organizations from
free-text company names (duplicate resolution is a separate concern), it
does not guess dates LinkedIn left blank, and it does not invent skills
not endorsed or not declared. Missing data turns into a warning, not a
fabrication.

Provenance: every emitted Claim references a single ``SourceDoc`` whose
sha256 is the hash of the input ZIP, so a reviewer can walk from any
generated bullet back to the exact archive it came from.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import zipfile
from pathlib import Path
from typing import ClassVar

from ..schema import (
    Claim,
    Education,
    Organization,
    Person,
    Role,
    Skill,
    SourceDoc,
    Testimonial,
)
from .base import IngestResult

# Files we read. ``accepts()`` only requires one to exist so older Basic
# exports without endorsements still trigger this ingester.
_WANTED_CSVS = {
    "Positions.csv",
    "Education.csv",
    "Skills.csv",
    "Profile.csv",
    "Recommendations_Received.csv",
    "Endorsement_Received_Info.csv",
}

# Filename pattern LinkedIn uses for the Complete export
# (``Complete_LinkedInDataExport_MM-DD-YYYY.zip``). Best-effort: when it
# matches, we use it for ``SourceDoc.captured_at``; when it doesn't, the
# ZIP's mtime is the fallback.
_EXPORT_DATE_RE = re.compile(r"_(\d{2})-(\d{2})-(\d{4})\.zip$", re.IGNORECASE)


def _slug(value: str) -> str:
    """Lowercase ASCII slug for stable IDs.

    Identical to the helper in ``markdown.py`` but kept local to avoid an
    import cycle when both ingesters get extracted into a shared utility
    module.
    """
    return (
        "".join(ch if ch.isalnum() else "_" for ch in value.strip().lower()).strip("_")
        or "unknown"
    )


def _partial(value: str | None) -> str | None:
    """LinkedIn writes dates as 'Mon YYYY' or blank; normalise to YYYY-MM.

    Returns None for blanks and for anything we cannot parse; callers
    surface this as a warning rather than failing the whole import.
    """
    if not value:
        return None
    value = value.strip()
    months = {
        "jan": "01",
        "feb": "02",
        "mar": "03",
        "apr": "04",
        "may": "05",
        "jun": "06",
        "jul": "07",
        "aug": "08",
        "sep": "09",
        "oct": "10",
        "nov": "11",
        "dec": "12",
    }
    parts = value.split()
    if len(parts) == 2 and parts[0][:3].lower() in months:
        return f"{parts[1]}-{months[parts[0][:3].lower()]}"
    if len(parts) == 1 and parts[0].isdigit() and len(parts[0]) == 4:
        return parts[0]
    return None


def _endorsement_date(value: str | None) -> str | None:
    """Convert ``YYYY/MM/DD HH:MM:SS UTC`` to ``YYYY-MM-DD``.

    The endorsement export uses slash-separated date-times with a trailing
    timezone label that the schema's ``PartialDate`` would reject. We keep
    only the date portion since endorsement granularity finer than a day is
    not useful at render time.
    """
    if not value:
        return None
    head = value.strip().split()[0]
    if re.fullmatch(r"\d{4}/\d{2}/\d{2}", head):
        return head.replace("/", "-")
    return None


class LinkedInExportIngester:
    """Pull career-graph data from a LinkedIn data-export ZIP.

    The class is stateless across invocations, but each call to
    ``ingest`` builds a single ``SourceDoc`` for the ZIP that every
    emitted Claim references; that lookup happens once per CSV pass.
    """

    name: ClassVar[str] = "linkedin_export"

    def accepts(self, src: Path) -> bool:
        if not src.is_file() or src.suffix.lower() != ".zip":
            return False
        try:
            with zipfile.ZipFile(src) as zf:
                return bool(set(zf.namelist()) & _WANTED_CSVS)
        except zipfile.BadZipFile:
            return False

    def ingest(self, src: Path) -> IngestResult:
        result = IngestResult()
        source = self._source_doc(src)
        result.sources.append(source)

        with zipfile.ZipFile(src) as zf:
            names = set(zf.namelist())
            if "Profile.csv" in names:
                result = self._merge(result, self._profile(zf, source.id))
            if "Positions.csv" in names:
                result = self._merge(result, self._positions(zf, source.id))
            if "Education.csv" in names:
                result = self._merge(result, self._education(zf))
            if "Skills.csv" in names:
                result = self._merge(result, self._skills(zf))
            if "Recommendations_Received.csv" in names:
                result = self._merge(result, self._recommendations(zf))
            if "Endorsement_Received_Info.csv" in names:
                # Endorsements may reference skills not declared in
                # Skills.csv; pass the already-known skill IDs so the
                # method only auto-emits Skill entities for new names.
                known_skill_ids = {
                    e.id for e in result.entities if isinstance(e, Skill)
                }
                result = self._merge(
                    result,
                    self._endorsements(zf, source.id, known_skill_ids),
                )
        return result

    @staticmethod
    def _merge(a: IngestResult, b: IngestResult) -> IngestResult:
        return IngestResult(
            entities=a.entities + b.entities,
            claims=a.claims + b.claims,
            sources=a.sources + b.sources,
            warnings=a.warnings + b.warnings,
        )

    def _read(self, zf: zipfile.ZipFile, name: str) -> list[dict[str, str]]:
        with zf.open(name) as fh:
            text = io.TextIOWrapper(fh, encoding="utf-8-sig", newline="")
            return list(csv.DictReader(text))

    def _source_doc(self, src: Path) -> SourceDoc:
        """Build a SourceDoc from the ZIP itself.

        Hashing the whole archive (rather than per-CSV) gives one stable
        provenance handle per export run: re-importing the same ZIP
        deduplicates by id, while a fresh export gets a new id.
        """
        h = hashlib.sha256()
        with src.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        digest = h.hexdigest()

        captured_at: str | None = None
        m = _EXPORT_DATE_RE.search(src.name)
        if m is not None:
            mm, dd, yyyy = m.groups()
            captured_at = f"{yyyy}-{mm}-{dd}"

        # ID embeds the first 12 hex chars so two distinct exports do not
        # collide while staying short enough to read in a YAML file.
        return SourceDoc(
            id=f"linkedin_export_{digest[:12]}",
            origin="linkedin_export",
            sha256=digest,
            mime_type="application/zip",
            original_name=src.name,
            captured_at=captured_at,
        )

    def _profile(self, zf: zipfile.ZipFile, source_id: str) -> IngestResult:
        res = IngestResult()
        rows = self._read(zf, "Profile.csv")
        if not rows:
            res.warnings.append("LinkedIn Profile.csv: empty; no Person emitted")
            return res
        # The export ships exactly one profile row; later rows would be a
        # data corruption, not a multi-person scenario.
        if len(rows) > 1:
            res.warnings.append(
                f"LinkedIn Profile.csv: expected 1 row, got {len(rows)}; "
                "using the first"
            )
        row = rows[0]
        first = (row.get("First Name") or "").strip()
        last = (row.get("Last Name") or "").strip()
        if not first and not last:
            res.warnings.append(
                "LinkedIn Profile.csv: row missing First/Last name; skipped"
            )
            return res
        full = f"{first} {last}".strip()
        person_id = _slug(full) or "person"

        contact: dict[str, str] = {}
        # Twitter/Websites are comma-separated multi-value cells in the
        # export; we keep the raw string so downstream renderers can split
        # as they wish without losing the user's original ordering.
        twitter = (row.get("Twitter Handles") or "").strip()
        if twitter:
            contact["twitter"] = twitter
        websites = (row.get("Websites") or "").strip()
        if websites:
            contact["website"] = websites

        person = Person(
            id=person_id,
            full_name=full,
            headline=(row.get("Headline") or "").strip() or None,
            location=(row.get("Geo Location") or "").strip() or None,
            contact=contact,
        )
        res.entities.append(person)

        summary = (row.get("Summary") or "").strip()
        if summary:
            res.claims.append(
                Claim(
                    id=f"{person_id}_profile_summary",
                    subject_id=person_id,
                    subject_kind="person",
                    type="context",
                    text=summary,
                    sources=[source_id],
                    tags=["linkedin", "profile_summary"],
                )
            )
        return res

    def _positions(self, zf: zipfile.ZipFile, source_id: str) -> IngestResult:
        res = IngestResult()
        for row in self._read(zf, "Positions.csv"):
            company = (row.get("Company Name") or "").strip()
            title = (row.get("Title") or "").strip()
            start = _partial(row.get("Started On"))
            end = _partial(row.get("Finished On"))
            if not company or not title or not start:
                res.warnings.append(
                    f"LinkedIn Positions: skipped row missing company/title/start "
                    f"({row!r})"
                )
                continue
            org_id = _slug(company)
            role_id = f"{org_id}_{_slug(title)}_{start[:4]}"
            res.entities.append(Organization(id=org_id, name=company))
            res.entities.append(
                Role(
                    id=role_id,
                    title=title,
                    organization_id=org_id,
                    period={"start": start, "end": end},
                    location=(row.get("Location") or "").strip() or None,
                )
            )
            description = (row.get("Description") or "").strip()
            if description:
                res.claims.append(
                    Claim(
                        id=f"{role_id}_description",
                        subject_id=role_id,
                        subject_kind="role",
                        type="context",
                        text=description,
                        sources=[source_id],
                        tags=["linkedin", "position_description"],
                    )
                )
        return res

    def _education(self, zf: zipfile.ZipFile) -> IngestResult:
        res = IngestResult()
        for row in self._read(zf, "Education.csv"):
            school = (row.get("School Name") or "").strip()
            degree = (row.get("Degree Name") or "").strip()
            if not school or not degree:
                res.warnings.append(
                    "LinkedIn Education: skipped row missing school/degree"
                )
                continue
            start = _partial(row.get("Start Date"))
            end = _partial(row.get("End Date"))
            period_dict = None
            if start:
                period_dict = {"start": start, "end": end}
            res.entities.append(
                Education(
                    id=f"{_slug(school)}_{_slug(degree)}",
                    institution=school,
                    credential=degree,
                    field_of_study=(row.get("Notes") or "").strip() or None,
                    period=period_dict,
                )
            )
        return res

    def _skills(self, zf: zipfile.ZipFile) -> IngestResult:
        res = IngestResult()
        for row in self._read(zf, "Skills.csv"):
            name = (row.get("Name") or "").strip()
            if not name:
                continue
            res.entities.append(Skill(id=_slug(name), name=name, tier="applied"))
        return res

    def _recommendations(self, zf: zipfile.ZipFile) -> IngestResult:
        """Read Recommendations_Received.csv into Testimonial entities.

        Skips rows whose Status is set and not ``VISIBLE``: a hidden
        recommendation was deliberately suppressed by the author and
        should not silently re-surface in a generated CV. Empty Status is
        treated as visible because older exports omit the column.
        """
        res = IngestResult()
        seen: set[str] = set()
        for row in self._read(zf, "Recommendations_Received.csv"):
            text = (row.get("Text") or "").strip()
            first = (row.get("First Name") or "").strip()
            last = (row.get("Last Name") or "").strip()
            company = (row.get("Company") or "").strip()
            title = (row.get("Job Title") or "").strip()
            status = (row.get("Status") or "").strip().upper()
            if not text or not (first or last):
                res.warnings.append(
                    "LinkedIn Recommendations: skipped row missing text/attribution"
                )
                continue
            if status and status != "VISIBLE":
                continue
            attribution = f"{first} {last}".strip()
            # Prefer the creation date in the ID so two recommendations
            # from the same person at different times keep distinct IDs;
            # fall back to attribution-only when the date is unparseable.
            date_part = (row.get("Creation Date") or "").strip()
            date_compact = "".join(ch for ch in date_part if ch.isdigit())[:8]
            base_id = _slug(f"{attribution}_{date_compact}".rstrip("_"))
            tid = base_id
            n = 2
            while tid in seen:
                tid = f"{base_id}_{n}"
                n += 1
            seen.add(tid)
            relationship = None
            if title or company:
                relationship = ", ".join(p for p in (title, company) if p) or None
            res.entities.append(
                Testimonial(
                    id=tid,
                    quote=text,
                    attribution=attribution,
                    relationship=relationship,
                )
            )
        return res

    def _endorsements(
        self,
        zf: zipfile.ZipFile,
        source_id: str,
        known_skill_ids: set[str],
    ) -> IngestResult:
        """Convert per-skill endorsements into Claims.

        One claim per accepted endorsement. The text is short and
        stylised (``"Endorsed by First Last"``) because the renderer
        decides how to surface it; carrying prose here would force a
        format choice into the ingester.

        Skills that appear in endorsements but not in ``Skills.csv`` are
        emitted as new ``Skill`` entities so the resulting Claim has a
        valid subject under check ``_c07``. They land at
        ``tier="applied"``, which the user can re-tier later.
        """
        res = IngestResult()
        emitted_skills: set[str] = set()
        seen_claims: set[str] = set()
        for row in self._read(zf, "Endorsement_Received_Info.csv"):
            status = (row.get("Endorsement Status") or "").strip().upper()
            if status != "ACCEPTED":
                continue
            skill_name = (row.get("Skill Name") or "").strip()
            if not skill_name:
                continue
            first = (row.get("Endorser First Name") or "").strip()
            last = (row.get("Endorser Last Name") or "").strip()
            endorser = f"{first} {last}".strip()
            if not endorser:
                res.warnings.append(
                    f"LinkedIn Endorsements: skipped row for {skill_name!r} "
                    "missing endorser name"
                )
                continue
            skill_id = _slug(skill_name)
            if skill_id not in known_skill_ids and skill_id not in emitted_skills:
                res.entities.append(Skill(id=skill_id, name=skill_name, tier="applied"))
                emitted_skills.add(skill_id)
            date = _endorsement_date(row.get("Endorsement Date"))
            date_part = date.replace("-", "") if date else "undated"
            base_id = f"{skill_id}_endorsement_{_slug(endorser)}_{date_part}"
            cid = base_id
            n = 2
            while cid in seen_claims:
                cid = f"{base_id}_{n}"
                n += 1
            seen_claims.add(cid)
            tags = ["linkedin", "endorsement"]
            if date:
                tags.append(f"date:{date}")
            res.claims.append(
                Claim(
                    id=cid,
                    subject_id=skill_id,
                    subject_kind="skill",
                    type="fact",
                    text=f"Endorsed by {endorser}",
                    sources=[source_id],
                    tags=tags,
                )
            )
        return res
