"""ORCID public record ingester.

ORCID (https://orcid.org) exposes every researcher's public record as
JSON via the public API. We pull the ``works`` collection and map each
work to a ``Publication`` entity. Biographical fields (``person``) are
not mapped automatically: a corpus already has a ``Person`` and we do
not want to silently overwrite it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import httpx

from ..schema import Publication
from .base import IngestResult

_API_ROOT = "https://pub.orcid.org/v3.0"
_ORCID_ID_LEN = 19  # "0000-0000-0000-000X"


def _slug(value: str) -> str:
    return (
        "".join(ch if ch.isalnum() else "_" for ch in value.strip().lower()).strip("_")
        or "publication"
    )


class OrcidIngester:
    """Fetch a researcher's public publication list from ORCID."""

    name: ClassVar[str] = "orcid"

    def __init__(
        self,
        *,
        orcid_id: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._orcid_id = orcid_id
        self._client = client

    def accepts(self, src: Path) -> bool:
        if not src.is_file() or src.suffix.lower() not in {".txt", ""}:
            return False
        try:
            body = src.read_text(encoding="utf-8").strip()
        except OSError:
            return False
        return len(body) == _ORCID_ID_LEN and body.count("-") == 3

    def ingest(self, src: Path) -> IngestResult:
        orcid_id = self._orcid_id
        if orcid_id is None and src.is_file():
            orcid_id = src.read_text(encoding="utf-8").strip()
        if not orcid_id:
            return IngestResult(warnings=["orcid: no orcid_id supplied"])

        headers = {"Accept": "application/json"}
        client = self._client or httpx.Client(
            base_url=_API_ROOT, headers=headers, timeout=15.0
        )
        try:
            works = client.get(f"/{orcid_id}/works").json()
        finally:
            if self._client is None:
                client.close()

        return self._to_result(works)

    def _to_result(self, works: dict[str, Any]) -> IngestResult:
        groups = works.get("group") if isinstance(works, dict) else None
        if not isinstance(groups, list):
            return IngestResult(warnings=["orcid: unexpected works payload"])

        publications: list[Publication] = []
        for group in groups:
            summaries = group.get("work-summary") if isinstance(group, dict) else None
            if not isinstance(summaries, list) or not summaries:
                continue
            summary = summaries[0]
            if not isinstance(summary, dict):
                continue
            title_obj = summary.get("title")
            title = ""
            if isinstance(title_obj, dict):
                title = (
                    title_obj.get("title", {}).get("value", "")
                    if isinstance(title_obj.get("title"), dict)
                    else ""
                )
            if not title:
                continue

            date = ""
            pub_date = summary.get("publication-date")
            if isinstance(pub_date, dict):
                year = pub_date.get("year", {})
                if isinstance(year, dict):
                    date = year.get("value", "") or ""

            venue = ""
            journal = summary.get("journal-title")
            if isinstance(journal, dict):
                venue = journal.get("value", "") or ""

            doi = ""
            ext_ids = summary.get("external-ids", {}).get("external-id", [])
            if isinstance(ext_ids, list):
                for ext in ext_ids:
                    if isinstance(ext, dict) and ext.get("external-id-type") == "doi":
                        value = ext.get("external-id-value", "")
                        if isinstance(value, str):
                            doi = value
                            break

            publications.append(
                Publication(
                    id=f"pub_{_slug(title)[:60]}",
                    title=title,
                    venue=venue or None,
                    date=date or None,
                    doi=doi or None,
                )
            )
        return IngestResult(entities=list(publications))
