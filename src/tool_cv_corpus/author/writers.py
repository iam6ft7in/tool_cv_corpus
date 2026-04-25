"""On-disk writers for authored entities and claims.

Each entity kind has a conventional directory under the corpus root.
Claims do not have an entity directory because they are not entities;
they live under ``claims/`` for organizational clarity, but the loader
walks every ``*.yaml`` and dispatches by the ``kind:`` discriminator, so
the directory is convention not mechanism.

YAML output is deliberately stable: keys serialised in field-declaration
order, scalars unquoted unless YAML rules require it, dates always
quoted (the schema's ``PartialDate`` is a string but unquoted ``2021``
parses as int). Reading back any file we just wrote must round-trip.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from ..schema import AnyEntity, Claim

# Maps entity ``kind`` to the directory name used by the bundled
# skeleton and by ``examples/corpus_jordan_taylor``. Kept here so a new
# entity kind has exactly one place to register its on-disk home.
DIRECTORY_BY_KIND: dict[str, str] = {
    "person": "persons",
    "organization": "organizations",
    "role": "roles",
    "project": "projects",
    "achievement": "achievements",
    "skill": "skills",
    "education": "education",
    "publication": "publications",
    "artifact": "artifacts",
    "testimonial": "testimonials",
    "cover_letter_seed": "cover_letter_seeds",
    "target": "targets",
    "source_doc": "sources",
}

CLAIMS_DIRECTORY = "claims"

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slug(value: str) -> str:
    """Lowercase ASCII slug, falling back to ``"item"`` for empties.

    Used to suggest IDs from natural-language fields (full name, role
    title, organization name). The user can always override the
    suggestion at the prompt; this is a convenience, not a constraint.
    """
    return _SLUG_RE.sub("_", value.strip().lower()).strip("_") or "item"


# Per-kind ID suggestion: which fields to slug-and-join, in order. The
# wizard offers the result as a default; the user can edit it before the
# entity is written.
_ID_RECIPES: dict[str, tuple[str, ...]] = {
    "person": ("full_name",),
    "organization": ("name",),
    "role": ("organization_id", "title"),
    "project": ("name",),
    "achievement": ("headline",),
    "skill": ("name",),
    "education": ("institution", "credential"),
    "publication": ("title",),
    "artifact": ("name",),
    "testimonial": ("attribution",),
    "cover_letter_seed": ("purpose",),
    "target": ("organization_name", "role_title"),
    "source_doc": ("original_name",),
}


def suggest_entity_id(
    kind: str,
    values: dict[str, Any],
    existing_ids: set[str],
) -> str:
    """Build a default ID from the fields that already have values.

    For ``Role``, ``period.start`` is appended when present so two roles
    at the same org with the same title still get distinct IDs (this is
    the same pattern used by the LinkedIn ingester).
    """
    parts: list[str] = []
    for field_name in _ID_RECIPES.get(kind, ()):
        v = values.get(field_name)
        if isinstance(v, str) and v.strip():
            parts.append(slug(v))
    if kind == "role":
        period = values.get("period")
        if isinstance(period, dict):
            start = period.get("start")
            if isinstance(start, str) and start[:4].isdigit():
                parts.append(start[:4])
    base = "_".join(parts) if parts else slug(kind)

    if base not in existing_ids:
        return base
    n = 2
    while f"{base}_{n}" in existing_ids:
        n += 1
    return f"{base}_{n}"


def _entity_path(root: Path, kind: str, entity_id: str) -> Path:
    directory = DIRECTORY_BY_KIND.get(kind)
    if directory is None:
        raise ValueError(f"unknown entity kind: {kind!r}")
    return root / directory / f"{entity_id}.yaml"


def _dump_yaml(payload: dict[str, Any]) -> str:
    """Render ``payload`` as YAML with stable, schema-friendly formatting.

    ``allow_unicode=True`` so users can include non-ASCII characters in
    names and quotes; ``sort_keys=False`` so the field order set by the
    Pydantic model survives to disk; ``default_flow_style=False`` so
    nested objects render as block mappings rather than ``{a: 1}``.
    """
    return yaml.safe_dump(
        payload,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )


def _model_to_dict(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(exclude_defaults=False, exclude_none=False)


def write_entity(root: Path, entity: AnyEntity) -> Path:
    """Persist ``entity`` under its conventional directory.

    Returns the absolute path written. Raises ``FileExistsError`` if the
    target file already exists; the wizard checks for collisions before
    calling so the user can override or re-suggest the ID.
    """
    target = _entity_path(root, entity.kind, entity.id)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError(target)

    payload = _model_to_dict(entity)
    # Move the discriminator to the front for readability; pydantic's
    # default order already places ``id`` second on every entity.
    ordered: dict[str, Any] = {"kind": payload.pop("kind")}
    ordered.update(payload)
    target.write_text(_dump_yaml(ordered), encoding="utf-8")
    return target


def write_claim(root: Path, claim: Claim) -> Path:
    """Persist ``claim`` under ``claims/<id>.yaml`` with the discriminator.

    The Claim model has no ``kind`` field, so the discriminator is added
    only on disk. The loader strips it back out before re-validating;
    keeping it here lets the loader's directory walk dispatch claims and
    entities from the same stream.
    """
    target = root / CLAIMS_DIRECTORY / f"{claim.id}.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError(target)

    payload = _model_to_dict(claim)
    ordered: dict[str, Any] = {"kind": "claim"}
    ordered.update(payload)
    target.write_text(_dump_yaml(ordered), encoding="utf-8")
    return target
