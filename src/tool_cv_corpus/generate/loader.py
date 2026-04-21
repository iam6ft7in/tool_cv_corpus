"""Corpus loader: on-disk YAML tree into an immutable in-memory ``Corpus``.

Where the validator is permissive and accumulates problems, this loader is
strict: any parse error, schema failure, or missing Person aborts with a
``CorpusLoadError``. The contract is that ``generate`` refuses to run on
an invalid corpus; callers should run ``cv-corpus validate`` first for a
full report.

The returned ``Corpus`` is deliberately immutable (``MappingProxyType``
over the entity and claim maps, ``tuple`` for the per-subject claim
lists) so downstream stages (scorer, selector, synthesizer) can treat
it as a stable snapshot and memoize against it without fearing mutation.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from pydantic import TypeAdapter, ValidationError

from ..io.yaml_loader import iter_yaml_files
from ..schema import AnyEntity, Claim, Visibility
from ..schema.base import Entity
from ..schema.entities import Person, Role, Skill
from ..schema.migrations import migrate

EntityKey = tuple[str, str]
"""``(kind, id)`` pair. IDs are only unique within a kind."""


class CorpusLoadError(ValueError):
    """Unrecoverable load failure.

    Raised on YAML parse errors, non-mapping YAML roots, schema validation
    failures, corpora with zero or multiple ``Person`` entities, and when
    ``root`` is not a directory. The message always names the offending
    file (when applicable) so users can jump straight to it.
    """


_VISIBILITY_RANK: dict[Visibility, int] = {"public": 0, "nda": 1, "private": 2}


def _visibility_allowed(v: Visibility, max_v: Visibility) -> bool:
    return _VISIBILITY_RANK[v] <= _VISIBILITY_RANK[max_v]


@dataclass(frozen=True)
class Corpus:
    """Validated, redaction-applied, supersession-resolved snapshot.

    Everything a scorer or selector needs is either here or derivable
    from here without another disk read. The ``Corpus`` never exposes:

    - entities whose ``visibility`` exceeds ``max_visibility``
    - claims that are superseded by an active successor
    - claims whose subject entity has been redacted out
    """

    root: Path
    max_visibility: Visibility
    entities: Mapping[EntityKey, Entity]
    claims_by_subject: Mapping[EntityKey, tuple[Claim, ...]]
    person: Person
    _skills_by_id: Mapping[str, Skill] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def claims_for(self, kind: str, ent_id: str) -> tuple[Claim, ...]:
        """Claims whose subject is ``(kind, ent_id)``.

        Returns an empty tuple when there are none; callers never need to
        guard against ``None`` and can iterate the result directly.
        """
        return self.claims_by_subject.get((kind, ent_id), ())

    @property
    def skills_by_id(self) -> Mapping[str, Skill]:
        """``skill.id -> Skill`` view for hierarchy walks and lookups."""
        return self._skills_by_id

    def roles_chronological(self) -> tuple[Role, ...]:
        """Roles sorted most-recent-first by ``period.start``.

        Partial dates sort lexicographically, which gives the correct
        order because ``YYYY-MM`` and ``YYYY`` share an ISO-ordered prefix.
        """
        roles = [
            e
            for (kind, _), e in self.entities.items()
            if kind == "role" and isinstance(e, Role)
        ]
        return tuple(sorted(roles, key=lambda r: r.period.start, reverse=True))


def load_corpus(
    root: Path,
    *,
    max_visibility: Visibility = "private",
) -> Corpus:
    """Load and return an immutable ``Corpus`` from ``root``.

    ``max_visibility`` is the redaction cap. ``"private"`` (default)
    keeps everything; ``"nda"`` drops ``private`` nodes; ``"public"`` drops
    both ``nda`` and ``private``. Callers that render or ship artifacts
    should pick the tightest cap appropriate for their destination.

    Raises ``CorpusLoadError`` on any parse or schema failure, on an
    absent or duplicated ``Person``, or on a non-directory ``root``.
    """
    root = Path(root)
    if not root.is_dir():
        raise CorpusLoadError(f"{root} is not a directory")

    entity_adapter: TypeAdapter[AnyEntity] = TypeAdapter(AnyEntity)
    claim_adapter: TypeAdapter[Claim] = TypeAdapter(Claim)

    raw_entities: dict[EntityKey, Entity] = {}
    raw_claims: list[Claim] = []

    for result in iter_yaml_files(root):
        if not result.ok:
            raise CorpusLoadError(f"{result.path}: {result.error}")

        assert result.data is not None  # narrowed by result.ok
        data = migrate(result.data)
        kind = data.get("kind")

        try:
            if kind == "claim":
                # ``Claim`` has no ``kind`` field; the discriminator is
                # used only by the walker to split streams. Strip it
                # before validating so ``extra="forbid"`` does not reject
                # a well-formed claim.
                payload = {k: v for k, v in data.items() if k != "kind"}
                raw_claims.append(claim_adapter.validate_python(payload))
            else:
                entity = entity_adapter.validate_python(data)
                raw_entities[(entity.kind, entity.id)] = entity
        except ValidationError as exc:
            first = exc.errors()[0]
            loc = ".".join(str(p) for p in first.get("loc", ()))
            raise CorpusLoadError(
                f"{result.path}: schema validation failed at "
                f"{loc or '<root>'}: {first['msg']}"
            ) from exc

    persons = [e for (k, _), e in raw_entities.items() if k == "person"]
    if not persons:
        raise CorpusLoadError(f"{root}: corpus has no Person entity")
    if len(persons) > 1:
        raise CorpusLoadError(
            f"{root}: corpus has {len(persons)} Person entities; "
            "exactly one is required"
        )
    person = persons[0]
    assert isinstance(person, Person)

    entities: dict[EntityKey, Entity] = {
        k: e
        for k, e in raw_entities.items()
        if _visibility_allowed(e.visibility, max_visibility)
    }

    claim_by_id: dict[str, Claim] = {c.id: c for c in raw_claims}

    def _is_active(claim: Claim) -> bool:
        """Claim survives if it is not redacted and has no active successor.

        Walks the ``superseded_by`` chain looking for a successor that is
        itself visibility-allowed. Broken chains (missing successor) are
        treated as active so partial imports still surface their latest
        known assertion.
        """
        if not _visibility_allowed(claim.visibility, max_visibility):
            return False
        cur_id = claim.superseded_by
        while cur_id is not None:
            nxt = claim_by_id.get(cur_id)
            if nxt is None:
                return True
            if _visibility_allowed(nxt.visibility, max_visibility):
                return False
            cur_id = nxt.superseded_by
        return True

    grouped: dict[EntityKey, list[Claim]] = {}
    for c in raw_claims:
        if not _is_active(c):
            continue
        key = (c.subject_kind, c.subject_id)
        if key not in entities:
            continue
        grouped.setdefault(key, []).append(c)

    skills_by_id: dict[str, Skill] = {
        k[1]: e for k, e in entities.items() if k[0] == "skill" and isinstance(e, Skill)
    }

    return Corpus(
        root=root,
        max_visibility=max_visibility,
        entities=MappingProxyType(entities),
        claims_by_subject=MappingProxyType({k: tuple(v) for k, v in grouped.items()}),
        person=person,
        _skills_by_id=MappingProxyType(skills_by_id),
    )
