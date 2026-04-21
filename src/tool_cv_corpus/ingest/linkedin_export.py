"""LinkedIn data-export ingester.

LinkedIn offers two exports:

- Basic (Positions.csv, Education.csv, Skills.csv, Profile.csv).
- Complete (adds Messages.csv, connections, endorsements, etc.).

Both are delivered as ZIPs. We only consume the career-relevant CSVs:
``Positions``, ``Education``, ``Skills``. Messages and connections are
personal data that does not belong in a career graph.

This ingester is intentionally conservative: it does not try to infer
organizations from free-text company names (duplicate resolution is a
separate concern), and it does not guess dates when LinkedIn left a
field blank. Missing data turns into a warning, not a fabrication.
"""

from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path
from typing import ClassVar

from ..schema import Education, Organization, Role, Skill
from .base import IngestResult

_WANTED_CSVS = {"Positions.csv", "Education.csv", "Skills.csv"}


def _slug(value: str) -> str:
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


class LinkedInExportIngester:
    """Pull Roles, Organizations, Skills, and Education from a LinkedIn ZIP."""

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
        with zipfile.ZipFile(src) as zf:
            names = set(zf.namelist())
            if "Positions.csv" in names:
                result = self._merge(result, self._positions(zf))
            if "Education.csv" in names:
                result = self._merge(result, self._education(zf))
            if "Skills.csv" in names:
                result = self._merge(result, self._skills(zf))
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

    def _positions(self, zf: zipfile.ZipFile) -> IngestResult:
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
            res.entities.append(Organization(id=org_id, name=company))
            res.entities.append(
                Role(
                    id=f"{org_id}_{_slug(title)}_{start[:4]}",
                    title=title,
                    organization_id=org_id,
                    period={"start": start, "end": end},
                    location=(row.get("Location") or "").strip() or None,
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
