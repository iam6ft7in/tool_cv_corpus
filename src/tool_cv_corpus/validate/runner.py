"""Ordered validator for corpus directories.

Checks run in a fixed order so later passes can assume the output of
earlier ones is trustworthy (parse before schema, schema before
cross-reference, cross-reference before redaction). Each check returns
a ``Check`` result with a status of ``ok`` / ``warn`` / ``error``; the
runner never raises on user data so the CLI can print a complete
report for fix-up, not just the first failure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import TypeAdapter, ValidationError

from ..io.yaml_loader import iter_yaml_files
from ..schema import AnyEntity, Claim
from ..schema.base import Entity
from ..schema.entities import Skill
from ..schema.migrations import migrate

Status = Literal["ok", "warn", "error"]

_PII_PATTERNS = {
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    "us_phone": re.compile(r"(?<!\d)(\d{3}[-.\s]?\d{3}[-.\s]?\d{4})(?!\d)"),
    "ssn": re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)"),
}


@dataclass
class Check:
    """One check outcome. ``detail`` is surfaced in the CLI table."""

    name: str
    status: Status
    detail: str = ""


@dataclass
class ValidationReport:
    checks: list[Check] = field(default_factory=list)

    @property
    def errors(self) -> list[Check]:
        return [c for c in self.checks if c.status == "error"]

    @property
    def warnings(self) -> list[Check]:
        return [c for c in self.checks if c.status == "warn"]


class ValidatorRunner:
    """Walk ``corpus`` and run 11 ordered checks.

    Cheap construction: all parsing happens in ``run()`` so tests can
    build a runner and introspect state afterwards.
    """

    def __init__(self, corpus: Path) -> None:
        self.corpus = Path(corpus)
        self._parsed: list[tuple[Path, dict[str, Any]]] = []
        self._entities: dict[tuple[str, str], Entity] = {}
        self._claims: list[Claim] = []
        self._parse_errors: list[str] = []

    def run(self) -> ValidationReport:
        report = ValidationReport()
        report.checks.append(self._c01_layout())
        report.checks.append(self._c02_parse_yaml())
        report.checks.append(self._c03_schema_conformance())
        report.checks.append(self._c04_no_duplicate_ids())
        report.checks.append(self._c05_foreign_keys())
        report.checks.append(self._c06_person_exists())
        report.checks.append(self._c07_claim_subjects())
        report.checks.append(self._c08_supersede_chain())
        report.checks.append(self._c09_skill_parents_acyclic())
        report.checks.append(self._c10_pii_in_public())
        report.checks.append(self._c11_redaction_dryrun())
        return report

    # --- Checks -------------------------------------------------------

    def _c01_layout(self) -> Check:
        if not self.corpus.is_dir():
            return Check("layout", "error", f"{self.corpus} is not a directory")
        any_content = any(self.corpus.rglob("*.yaml")) or any(self.corpus.rglob("*.md"))
        if not any_content:
            return Check(
                "layout",
                "warn",
                f"{self.corpus} contains no .yaml or .md files",
            )
        return Check("layout", "ok", "")

    def _c02_parse_yaml(self) -> Check:
        for result in iter_yaml_files(self.corpus):
            if result.ok:
                assert result.data is not None
                self._parsed.append((result.path, result.data))
            else:
                self._parse_errors.append(f"{result.path}: {result.error}")
        if self._parse_errors:
            return Check(
                "parse_yaml",
                "error",
                f"{len(self._parse_errors)} file(s) failed to parse",
            )
        return Check("parse_yaml", "ok", f"{len(self._parsed)} file(s) parsed")

    def _c03_schema_conformance(self) -> Check:
        adapter: TypeAdapter[AnyEntity] = TypeAdapter(AnyEntity)
        failures: list[str] = []
        for path, raw in self._parsed:
            try:
                data = migrate(raw)
                entity = adapter.validate_python(data)
            except ValidationError as exc:
                failures.append(f"{path}: {exc.errors()[0]['msg']}")
                continue
            self._entities[(entity.kind, entity.id)] = entity
        if failures:
            return Check(
                "schema_conformance",
                "error",
                "; ".join(failures[:3]) + ("; ..." if len(failures) > 3 else ""),
            )
        return Check(
            "schema_conformance",
            "ok",
            f"{len(self._entities)} entities validated",
        )

    def _c04_no_duplicate_ids(self) -> Check:
        seen: set[tuple[str, str]] = set()
        dupes: list[str] = []
        for path, raw in self._parsed:
            key = (str(raw.get("kind", "")), str(raw.get("id", "")))
            if key in seen:
                dupes.append(f"{key[0]}:{key[1]} ({path})")
            seen.add(key)
        if dupes:
            return Check("no_duplicate_ids", "error", "; ".join(dupes[:5]))
        return Check("no_duplicate_ids", "ok", "")

    def _c05_foreign_keys(self) -> Check:
        missing: list[str] = []
        ids_by_kind: dict[str, set[str]] = {}
        for kind, ent_id in self._entities:
            ids_by_kind.setdefault(kind, set()).add(ent_id)

        for (kind, ent_id), entity in self._entities.items():
            data = entity.model_dump()
            for ref_field, ref_kind in (
                ("organization_id", "organization"),
                ("role_id", "role"),
                ("project_id", "project"),
                ("parent_id", "skill"),
            ):
                val = data.get(ref_field)
                if val and val not in ids_by_kind.get(ref_kind, set()):
                    missing.append(
                        f"{kind}:{ent_id}.{ref_field} -> {ref_kind}:{val} (absent)"
                    )
            for list_field, ref_kind in (
                ("skill_ids", "skill"),
                ("achievement_ids", "achievement"),
                ("project_ids", "project"),
                ("emphasis_skill_ids", "skill"),
                ("avoid_skill_ids", "skill"),
            ):
                for item in data.get(list_field, []) or []:
                    if item not in ids_by_kind.get(ref_kind, set()):
                        missing.append(
                            f"{kind}:{ent_id}.{list_field}[] -> "
                            f"{ref_kind}:{item} (absent)"
                        )
        if missing:
            return Check(
                "foreign_keys",
                "error",
                f"{len(missing)} broken reference(s); "
                + "; ".join(missing[:3])
                + ("; ..." if len(missing) > 3 else ""),
            )
        return Check("foreign_keys", "ok", "")

    def _c06_person_exists(self) -> Check:
        persons = [k for k in self._entities if k[0] == "person"]
        if not persons:
            return Check(
                "person_exists",
                "error",
                "no Person entity found",
            )
        if len(persons) > 1:
            return Check(
                "person_exists",
                "warn",
                f"{len(persons)} Person entities; only one is expected in v0.1.0",
            )
        return Check("person_exists", "ok", "")

    def _c07_claim_subjects(self) -> Check:
        adapter: TypeAdapter[Claim] = TypeAdapter(Claim)
        invalid: list[str] = []
        for path, raw in self._parsed:
            if raw.get("kind") != "claim":
                continue
            # ``Claim`` has no ``kind`` field; strip the discriminator
            # before validation to match the loader's behavior.
            payload = {k: v for k, v in migrate(raw).items() if k != "kind"}
            try:
                claim = adapter.validate_python(payload)
            except ValidationError as exc:
                invalid.append(f"{path}: {exc.errors()[0]['msg']}")
                continue
            self._claims.append(claim)
            if (claim.subject_kind, claim.subject_id) not in self._entities:
                invalid.append(
                    f"{path}: claim subject "
                    f"{claim.subject_kind}:{claim.subject_id} not found"
                )
        if invalid:
            return Check("claim_subjects", "error", "; ".join(invalid[:3]))
        return Check("claim_subjects", "ok", f"{len(self._claims)} claim(s)")

    def _c08_supersede_chain(self) -> Check:
        by_id = {c.id: c for c in self._claims}
        issues: list[str] = []
        for claim in self._claims:
            if claim.superseded_by and claim.superseded_by not in by_id:
                issues.append(
                    f"{claim.id} superseded_by {claim.superseded_by} (missing)"
                )
        for claim in self._claims:
            seen: set[str] = set()
            cur = claim
            while cur.superseded_by:
                if cur.id in seen:
                    issues.append(f"cycle involving claim {claim.id}")
                    break
                seen.add(cur.id)
                nxt = by_id.get(cur.superseded_by)
                if nxt is None:
                    break
                cur = nxt
        if issues:
            return Check("supersede_chain", "error", "; ".join(issues[:3]))
        return Check("supersede_chain", "ok", "")

    def _c09_skill_parents_acyclic(self) -> Check:
        skills = {
            k[1]: cast(Skill, v) for k, v in self._entities.items() if k[0] == "skill"
        }
        cycles: list[str] = []
        for start_id in skills:
            seen: set[str] = set()
            cur: Skill | None = skills[start_id]
            while cur is not None:
                if cur.id in seen:
                    cycles.append(start_id)
                    break
                seen.add(cur.id)
                if cur.parent_id is None:
                    break
                cur = skills.get(cur.parent_id)
        if cycles:
            return Check(
                "skill_parents_acyclic",
                "error",
                f"cycle(s) via: {', '.join(sorted(set(cycles)))}",
            )
        return Check("skill_parents_acyclic", "ok", "")

    def _c10_pii_in_public(self) -> Check:
        """Flag obvious PII tokens that leak into ``visibility=public`` content.

        This is a heuristic, not a compliance check: the intent is to
        catch copy-paste slips (a phone number in an achievement headline)
        before the corpus ships publicly. An explicit public ``email`` in
        ``Person.contact`` is expected and not flagged.
        """
        hits: list[str] = []
        for (kind, ent_id), entity in self._entities.items():
            if entity.visibility != "public":
                continue
            data = entity.model_dump(exclude_defaults=True)
            for pii_kind, pattern in _PII_PATTERNS.items():
                for field_name, value in data.items():
                    if field_name == "contact" and pii_kind == "email":
                        continue  # contact emails are expected
                    if not isinstance(value, str):
                        continue
                    if pattern.search(value):
                        hits.append(f"{kind}:{ent_id}.{field_name} ~{pii_kind}")
        if hits:
            return Check(
                "pii_in_public",
                "warn",
                f"{len(hits)} suspected PII token(s): "
                + "; ".join(hits[:3])
                + ("; ..." if len(hits) > 3 else ""),
            )
        return Check("pii_in_public", "ok", "")

    def _c11_redaction_dryrun(self) -> Check:
        """Confirm a default 'public' render drops every non-public node.

        Full redaction profiles live in a later release; this dry-run
        just counts how many entities and claims *would* be filtered out
        under the strictest profile so users can eyeball the loss.
        """
        non_public_entities = [
            k for k, v in self._entities.items() if v.visibility != "public"
        ]
        non_public_claims = [c for c in self._claims if c.visibility != "public"]
        if not (non_public_entities or non_public_claims):
            return Check("redaction_dryrun", "ok", "all-public corpus")
        return Check(
            "redaction_dryrun",
            "ok",
            f"{len(non_public_entities)} entities + "
            f"{len(non_public_claims)} claims would be hidden under 'public'",
        )
