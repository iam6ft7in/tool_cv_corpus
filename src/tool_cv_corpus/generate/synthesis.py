"""Two-pass LLM synthesis: headline + summary, then per-role bullets (v0.2 M4).

Consumes a ``Corpus`` plus a ``Selection`` and produces a
``RenderedResume`` ready for any registered renderer. The LLM is used
*only* for prose synthesis: which claims to show, how to rank them, and
how to redact them is all decided upstream (loader, scorer, selector).
This layer is the only place a model is allowed to invent sentences, and
it runs behind two safeguards:

1. **Structured output.** Every LLM call goes through Anthropic tool-use
   with an ``input_schema`` derived from a narrow Pydantic model, so the
   response either validates or we raise, never "parse a best-effort
   JSON string."
2. **No new facts.** Rewritten bullets are checked for numeric tokens
   (dollars, percents, plain integers) that do not appear in the source
   claim or subject entity. Any such token triggers a soft fallback to
   the original ``Claim.text``. This catches the most dangerous
   hallucination mode (fabricated metrics) without needing a full
   factual-consistency model.

Pass A is one call for the whole resume. Pass B is one call per role so
a later re-run with one role edited does not invalidate the cache for
every other role. Both passes are skipped when there is nothing to
rewrite; a corpus without claims still produces a valid
``RenderedResume`` with person, roles, skills, and education.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..render import RenderedResume, RenderedSection
from ..schema import (
    Achievement,
    Claim,
    Education,
    Organization,
    Publication,
    Role,
    Skill,
    Target,
    Testimonial,
)
from .llm.base import LLMProvider, Msg, Tool
from .loader import Corpus
from .scoring import ScoreBreakdown
from .selection import Selection

# --- Structured-output models -------------------------------------------


class PassAOutput(BaseModel):
    """Shape returned by the headline+summary LLM call.

    Constraints are documented in the prompt rather than enforced here
    (a 13-word headline is worth keeping over a retry), so callers that
    need stricter limits can post-process.
    """

    model_config = ConfigDict(extra="forbid")
    headline: str = Field(..., min_length=1)
    summary: str = Field(..., min_length=1)


class PassBBullet(BaseModel):
    """One rewritten bullet bound to its source claim.

    ``claim_id`` is required so the caller can map the LLM's output back
    to the original Claim for the no-new-facts check.
    """

    model_config = ConfigDict(extra="forbid")
    claim_id: str = Field(..., min_length=1)
    rewritten: str = Field(..., min_length=1)


class PassBOutput(BaseModel):
    """Shape returned by a per-role bullet-rewrite LLM call."""

    model_config = ConfigDict(extra="forbid")
    bullets: list[PassBBullet] = Field(default_factory=list)


# --- Tool definitions ---------------------------------------------------


def _pass_a_tool() -> Tool:
    return Tool(
        name="emit_headline_and_summary",
        description=(
            "Emit the tailored headline and summary for the top of the "
            "resume. Call exactly once."
        ),
        input_schema=PassAOutput.model_json_schema(),
    )


def _pass_b_tool() -> Tool:
    return Tool(
        name="emit_bullets",
        description=(
            "Emit rewritten bullets for every claim shown, one entry per "
            "input claim. Preserve every fact in the source; do not "
            "introduce metrics, numbers, or proper nouns that are not "
            "already in the source. Call exactly once."
        ),
        input_schema=PassBOutput.model_json_schema(),
    )


# --- Prompts ------------------------------------------------------------


_PASS_A_SYSTEM = "\n".join(
    [
        "You are rewriting the top of a resume for one specific job.",
        "",
        "You must:",
        "- Produce a single headline of at most 12 words that matches the",
        "  target role and organization.",
        "- Produce a summary of at most 3 sentences that draws only on the",
        "  supplied claims.",
        "- Never introduce numbers, metrics, proper nouns, or claims absent",
        "  from the supplied data.",
        "- Prefer the candidate's own wording where it already fits.",
        "",
        "Return the result by calling the `emit_headline_and_summary` tool.",
    ]
)


_PASS_B_SYSTEM = "\n".join(
    [
        "You are rewriting resume bullets for one role.",
        "",
        "You must:",
        "- Produce exactly one rewritten bullet per claim supplied.",
        "- Each bullet must be a single sentence, aligned to the target",
        "  job's vocabulary.",
        "- Preserve every metric, number, percent, and proper noun from",
        "  the source claim.",
        "- Do not add metrics, numbers, percents, or proper nouns absent",
        "  from the source claim.",
        "- Keep the bullet compact: no lead-ins like 'Responsible for',",
        "  no filler.",
        "",
        "Return the result by calling the `emit_bullets` tool exactly once.",
    ]
)


def _format_target(target: Target) -> str:
    lines = [
        f"Target role: {target.role_title}",
        f"Target organization: {target.organization_name}",
    ]
    if target.requirements:
        lines.append("Target requirements:")
        lines.extend(f"- {req}" for req in target.requirements)
    return "\n".join(lines)


def _format_claims_for_prompt(claims: Iterable[Claim]) -> str:
    """Emit a deterministic JSON array of claims for the prompt body.

    We send JSON rather than prose so the LLM cannot confuse metadata
    with instruction text; ``claim_id`` is required on the way back so
    the no-new-facts check can find the source.
    """
    payload = [{"claim_id": c.id, "type": c.type, "text": c.text} for c in claims]
    return json.dumps(payload, indent=2, ensure_ascii=False)


# --- No-new-facts guard --------------------------------------------------

_NUMERIC_TOKEN = re.compile(r"\$?[\d]+(?:[\d,.]*\d)?%?")
"""Match dollar amounts, percentages, and plain integers/decimals.

Examples matched: ``$2M``-adjacent '2', ``$2,500,000``, ``50%``,
``12.3``, ``1``. We intentionally under-match words-with-digits
(``python3``) and version strings (``v2.1.3``) because those are
identifiers, not the hallucinated metrics we care about.
"""


def _extract_numeric_tokens(text: str) -> set[str]:
    return set(_NUMERIC_TOKEN.findall(text))


def _introduces_new_facts(source: str, rewritten: str) -> bool:
    """True if ``rewritten`` contains a numeric token absent from ``source``.

    Deliberately a soft check: reorderings, synonyms, and completely
    different sentence structures are fine. Only numeric-fact drift
    triggers a fallback. Future versions can add named-entity checks.
    """
    source_tokens = _extract_numeric_tokens(source)
    out_tokens = _extract_numeric_tokens(rewritten)
    return bool(out_tokens - source_tokens)


# --- Synthesis pipeline -------------------------------------------------


def synthesize(
    corpus: Corpus,
    target: Target,
    selection: Selection,
    scores: dict[str, ScoreBreakdown],
    provider: LLMProvider,
    *,
    model: str | None = None,
    max_tokens: int = 2048,
    temperature: float = 0.3,
) -> RenderedResume:
    """Run both LLM passes and assemble a ``RenderedResume``.

    Determinism: for fixed inputs and a deterministic provider (or a
    cache hit for every call) the output is byte-identical. The default
    temperature of 0.3 is low because this is a selection-constrained
    rewrite task, not brainstorming.

    Fault tolerance: when the LLM output fails the no-new-facts check
    for a bullet, the original ``Claim.text`` is used instead. Pass A
    failures (no tool_use block) propagate as ``SynthesisError`` because
    a missing headline/summary is a resume-visible regression; Pass B
    failures fall back silently per-claim.
    """
    claim_by_id = _index_claims_by_id(corpus)

    pass_a = _run_pass_a(
        corpus=corpus,
        target=target,
        selection=selection,
        claim_by_id=claim_by_id,
        provider=provider,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
    )

    sections = _run_all_pass_b(
        corpus=corpus,
        target=target,
        selection=selection,
        claim_by_id=claim_by_id,
        provider=provider,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
    )

    return _assemble_rendered_resume(
        corpus=corpus,
        target=target,
        selection=selection,
        pass_a=pass_a,
        sections=sections,
        scores=scores,
    )


class SynthesisError(RuntimeError):
    """Raised when a required LLM call did not return structured output."""


# --- Pass A (headline + summary) ----------------------------------------


def _run_pass_a(
    *,
    corpus: Corpus,
    target: Target,
    selection: Selection,
    claim_by_id: dict[str, Claim],
    provider: LLMProvider,
    model: str | None,
    max_tokens: int,
    temperature: float,
) -> PassAOutput | None:
    """Call the LLM for headline+summary, or return ``None`` if skipped.

    Skipped when the selection has no summary claims; we would rather
    surface an empty headline section than invite a hallucination from
    a model prompted only with the target description.
    """
    if not selection.summary_claim_ids:
        return None

    claims = [
        claim_by_id[cid] for cid in selection.summary_claim_ids if cid in claim_by_id
    ]
    if not claims:
        return None

    user_msg = (
        f"{_format_target(target)}\n\n"
        f"Candidate: {corpus.person.full_name}"
        + (f" ({corpus.person.headline})" if corpus.person.headline else "")
        + "\n\n"
        f"Claims to draw on:\n{_format_claims_for_prompt(claims)}"
    )

    resp = provider.complete(
        system=_PASS_A_SYSTEM,
        messages=[Msg(role="user", content=user_msg)],
        tools=[_pass_a_tool()],
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    if resp.tool_use is None:
        raise SynthesisError(
            "Pass A: model did not call emit_headline_and_summary tool"
        )
    return PassAOutput.model_validate(resp.tool_use)


# --- Pass B (per-role bullet rewrites) ----------------------------------


def _run_all_pass_b(
    *,
    corpus: Corpus,
    target: Target,
    selection: Selection,
    claim_by_id: dict[str, Claim],
    provider: LLMProvider,
    model: str | None,
    max_tokens: int,
    temperature: float,
) -> list[RenderedSection]:
    """Run Pass B once per role; return ordered ``RenderedSection`` list.

    One section per role in selection order. When a role has no claims
    anywhere in the selection (not under itself nor its achievements),
    the section is omitted so the renderer does not emit empty headers.
    """
    sections: list[RenderedSection] = []
    for role_id in selection.role_ids:
        role_claims = _collect_role_claims(
            corpus=corpus,
            role_id=role_id,
            selection=selection,
            claim_by_id=claim_by_id,
        )
        if not role_claims:
            continue

        bullets = _run_pass_b_for_role(
            corpus=corpus,
            target=target,
            role_id=role_id,
            role_claims=role_claims,
            claim_by_id=claim_by_id,
            provider=provider,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        if bullets:
            sections.append(
                RenderedSection(
                    name=f"role:{role_id}",
                    kind="bullets",
                    bullets=bullets,
                )
            )
    return sections


def _collect_role_claims(
    *,
    corpus: Corpus,
    role_id: str,
    selection: Selection,
    claim_by_id: dict[str, Claim],
) -> list[Claim]:
    """Claims attached to a role or to any of its selected achievements.

    Role-level claims come first, then per-achievement claims in
    selection order. The order is what the LLM sees and therefore what
    the reader ends up seeing, so determinism matters.
    """
    ordered: list[Claim] = []
    seen: set[str] = set()

    for cid in selection.claim_ids_by_subject.get(("role", role_id), ()):
        if cid in seen:
            continue
        seen.add(cid)
        claim = claim_by_id.get(cid)
        if claim is not None:
            ordered.append(claim)

    for ach_id in selection.achievement_ids_by_role.get(role_id, ()):
        for cid in selection.claim_ids_by_subject.get(("achievement", ach_id), ()):
            if cid in seen:
                continue
            seen.add(cid)
            claim = claim_by_id.get(cid)
            if claim is not None:
                ordered.append(claim)

    return ordered


def _run_pass_b_for_role(
    *,
    corpus: Corpus,
    target: Target,
    role_id: str,
    role_claims: list[Claim],
    claim_by_id: dict[str, Claim],
    provider: LLMProvider,
    model: str | None,
    max_tokens: int,
    temperature: float,
) -> list[str]:
    """Rewrite claims for one role, applying the no-new-facts fallback.

    Returns a list of bullet strings in the same order as ``role_claims``.
    If the LLM refuses to use the tool, or returns a bullet that
    introduces new numeric facts, we fall back to the original
    ``Claim.text`` for that position so the section is never empty.
    """
    role = corpus.entities.get(("role", role_id))
    role_desc = ""
    if isinstance(role, Role):
        role_desc = f"Role: {role.title}"
        org = corpus.entities.get(("organization", role.organization_id))
        if isinstance(org, Organization):
            role_desc += f" at {org.name}"

    user_msg = (
        f"{_format_target(target)}\n\n"
        f"{role_desc}\n\n"
        f"Source claims:\n{_format_claims_for_prompt(role_claims)}"
    )

    try:
        resp = provider.complete(
            system=_PASS_B_SYSTEM,
            messages=[Msg(role="user", content=user_msg)],
            tools=[_pass_b_tool()],
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )
    except Exception:
        return [c.text for c in role_claims]

    parsed = _parse_pass_b(resp.tool_use)
    if parsed is None:
        return [c.text for c in role_claims]

    rewrites_by_id = {b.claim_id: b.rewritten for b in parsed.bullets}

    out: list[str] = []
    for claim in role_claims:
        rewritten = rewrites_by_id.get(claim.id)
        if rewritten is None:
            out.append(claim.text)
            continue
        if _introduces_new_facts(claim.text, rewritten):
            out.append(claim.text)
            continue
        out.append(rewritten)
    return out


def _parse_pass_b(tool_use: dict[str, Any] | None) -> PassBOutput | None:
    if tool_use is None:
        return None
    try:
        return PassBOutput.model_validate(tool_use)
    except Exception:
        return None


# --- RenderedResume assembly --------------------------------------------


def _index_claims_by_id(corpus: Corpus) -> dict[str, Claim]:
    out: dict[str, Claim] = {}
    for claims in corpus.claims_by_subject.values():
        for claim in claims:
            out[claim.id] = claim
    return out


def _assemble_rendered_resume(
    *,
    corpus: Corpus,
    target: Target,
    selection: Selection,
    pass_a: PassAOutput | None,
    sections: list[RenderedSection],
    scores: dict[str, ScoreBreakdown],
) -> RenderedResume:
    """Build the final model from corpus lookups + LLM prose.

    Education, publications, and testimonials pass through from the
    corpus unfiltered (bar redaction, which the loader already did).
    v0.2 does not target-score these; a future milestone can add
    per-section selection without changing the renderer contract.
    """
    role_entities: list[Role] = []
    org_ids_needed: set[str] = set()
    for rid in selection.role_ids:
        entity = corpus.entities.get(("role", rid))
        if isinstance(entity, Role):
            role_entities.append(entity)
            org_ids_needed.add(entity.organization_id)

    org_entities: list[Organization] = []
    for oid in sorted(org_ids_needed):
        entity = corpus.entities.get(("organization", oid))
        if isinstance(entity, Organization):
            org_entities.append(entity)

    achievement_entities: list[Achievement] = []
    seen_ach: set[str] = set()
    for rid in selection.role_ids:
        for aid in selection.achievement_ids_by_role.get(rid, ()):
            if aid in seen_ach:
                continue
            seen_ach.add(aid)
            entity = corpus.entities.get(("achievement", aid))
            if isinstance(entity, Achievement):
                achievement_entities.append(entity)

    skill_entities: list[Skill] = []
    for sid in selection.skill_ids:
        skill = corpus.skills_by_id.get(sid)
        if skill is not None:
            skill_entities.append(skill)

    education_entities = [
        e
        for (kind, _), e in corpus.entities.items()
        if kind == "education" and isinstance(e, Education)
    ]
    publication_entities = [
        e
        for (kind, _), e in corpus.entities.items()
        if kind == "publication" and isinstance(e, Publication)
    ]
    testimonial_entities = [
        e
        for (kind, _), e in corpus.entities.items()
        if kind == "testimonial" and isinstance(e, Testimonial)
    ]

    metadata = {
        "target_id": target.id,
        "target_role_title": target.role_title,
        "target_organization": target.organization_name,
        "selected_roles": str(len(role_entities)),
        "selected_claims": str(
            sum(len(v) for v in selection.claim_ids_by_subject.values())
        ),
        "summary_claim_count": str(len(selection.summary_claim_ids)),
        "scored_claims": str(len(scores)),
    }

    return RenderedResume(
        person=corpus.person,
        headline=pass_a.headline if pass_a is not None else None,
        summary=pass_a.summary if pass_a is not None else None,
        roles=role_entities,
        organizations=org_entities,
        achievements=achievement_entities,
        skills=skill_entities,
        education=education_entities,
        publications=publication_entities,
        testimonials=testimonial_entities,
        sections=sections,
        metadata=metadata,
    )
