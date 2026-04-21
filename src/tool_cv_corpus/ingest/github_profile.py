"""GitHub profile ingester.

Pulls a user's public profile plus their top public repositories via
the REST API and maps them onto corpus entities:

- the user -> Person (or a claim on an existing Person if IDs collide),
- each repo -> Artifact with ``type='repo'``,
- distinct languages across repos -> Skill entries at ``applied`` tier.

Only public data is read and only the fields relevant to a CV are
kept. We do not list the user's followers, stars, or social graph:
those belong to LinkedIn, not a career corpus.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import httpx

from ..schema import Artifact, Person, Skill
from .base import IngestResult

_API_ROOT = "https://api.github.com"


def _slug(value: str) -> str:
    return (
        "".join(ch if ch.isalnum() else "_" for ch in value.strip().lower()).strip("_")
        or "unknown"
    )


class GithubProfileIngester:
    """Fetch a user's public profile + repos from GitHub."""

    name: ClassVar[str] = "github_profile"

    def __init__(
        self,
        *,
        username: str | None = None,
        token: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._username = username
        self._token = token
        self._client = client

    def accepts(self, src: Path) -> bool:
        """Stub path-based check.

        This ingester is primarily used via the CLI's ``--username`` flag,
        not a file. A text file containing exactly a bare username is
        accepted as a convenience.
        """
        if not src.is_file() or src.suffix.lower() not in {".txt", ""}:
            return False
        try:
            body = src.read_text(encoding="utf-8").strip()
        except OSError:
            return False
        return body.isidentifier() or "-" in body

    def ingest(self, src: Path) -> IngestResult:
        username = self._username
        if username is None and src.is_file():
            username = src.read_text(encoding="utf-8").strip()
        if not username:
            return IngestResult(
                warnings=["github_profile: no username supplied"],
            )
        headers = {"Accept": "application/vnd.github+json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        client = self._client or httpx.Client(
            base_url=_API_ROOT, headers=headers, timeout=15.0
        )
        try:
            user = client.get(f"/users/{username}").json()
            repos = client.get(
                f"/users/{username}/repos",
                params={"per_page": 30, "sort": "updated"},
            ).json()
        finally:
            if self._client is None:
                client.close()

        return self._to_result(user, repos, username)

    def _to_result(
        self,
        user: dict[str, Any],
        repos: list[dict[str, Any]],
        username: str,
    ) -> IngestResult:
        if not isinstance(user, dict) or "login" not in user:
            return IngestResult(
                warnings=[f"github_profile: unexpected response for {username}"]
            )
        person = Person(
            id=_slug(username),
            full_name=user.get("name") or user["login"],
            headline=user.get("bio") or None,
            location=user.get("location") or None,
            contact={
                "github": user.get("html_url", ""),
                "website": user.get("blog") or "",
                "email": user.get("email") or "",
            },
        )
        artifacts: list[Artifact] = []
        languages: set[str] = set()
        for repo in repos:
            if not isinstance(repo, dict):
                continue
            if repo.get("fork"):
                continue
            artifacts.append(
                Artifact(
                    id=f"repo_{_slug(repo['full_name'])}",
                    name=repo["name"],
                    type="repo",
                    url=repo.get("html_url") or None,
                    description=repo.get("description") or None,
                )
            )
            lang = repo.get("language")
            if isinstance(lang, str) and lang:
                languages.add(lang)

        skills = [
            Skill(id=_slug(lang), name=lang, tier="applied")
            for lang in sorted(languages)
        ]
        entities = [person, *artifacts, *skills]
        return IngestResult(entities=entities)
