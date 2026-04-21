"""Tests for the v0.2 synthesis layer.

Uses a mock ``LLMProvider`` that returns canned ``LLMResponse``s, so the
tests exercise the real synthesis pipeline end-to-end without network
and without spend. The mock also records every call so we can assert on
the prompt shape where that matters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from tool_cv_corpus.generate.llm.base import LLMResponse, Msg, Tool
from tool_cv_corpus.generate.loader import load_corpus
from tool_cv_corpus.generate.scoring import score_claims
from tool_cv_corpus.generate.selection import select
from tool_cv_corpus.generate.synthesis import (
    SynthesisError,
    _extract_numeric_tokens,
    _introduces_new_facts,
    synthesize,
)
from tool_cv_corpus.render import RenderedResume
from tool_cv_corpus.schema.entities import Target

# --- Fixture helpers -----------------------------------------------------


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _person(root: Path) -> None:
    _write(
        root / "persons" / "p.yaml",
        "kind: person\nid: p\nfull_name: Pat Q\nheadline: Staff Engineer\n",
    )


def _org(root: Path, org_id: str = "o") -> None:
    _write(
        root / "organizations" / f"{org_id}.yaml",
        f"kind: organization\nid: {org_id}\nname: {org_id.upper()}\n",
    )


def _role(
    root: Path,
    role_id: str,
    *,
    org_id: str = "o",
    start: str = "2020-01",
    end: str | None = "2024-12",
    achievement_ids: list[str] | None = None,
) -> None:
    end_line = f"  end: '{end}'\n" if end else ""
    ach_line = ""
    if achievement_ids:
        ach_line = "achievement_ids:\n" + "".join(f"  - {a}\n" for a in achievement_ids)
    _write(
        root / "roles" / f"{role_id}.yaml",
        f"kind: role\nid: {role_id}\ntitle: Engineer\n"
        f"organization_id: {org_id}\n"
        f"period:\n  start: '{start}'\n{end_line}{ach_line}",
    )


def _achievement(root: Path, ach_id: str, *, role_id: str = "r") -> None:
    _write(
        root / "achievements" / f"{ach_id}.yaml",
        f"kind: achievement\nid: {ach_id}\nheadline: {ach_id}\nrole_id: {role_id}\n",
    )


def _claim(
    root: Path,
    claim_id: str,
    subject_kind: str,
    subject_id: str,
    *,
    text: str = "did a thing",
    ctype: str = "outcome",
) -> None:
    _write(
        root / "claims" / f"{claim_id}.yaml",
        f"kind: claim\nid: {claim_id}\nsubject_id: {subject_id}\n"
        f"subject_kind: {subject_kind}\ntype: {ctype}\ntext: {text}\n",
    )


def _target() -> Target:
    return Target(
        id="t",
        role_title="Senior Engineer",
        organization_name="Contoso",
        requirements=["Python", "distributed systems"],
    )


def _build(tmp_path: Path) -> tuple[Any, Any, Any]:
    """Return (corpus, target, selection) for the standard fixture."""
    corpus = load_corpus(tmp_path)
    target = _target()
    scores = score_claims(corpus, target, now="2025-01")
    selection = select(corpus, target, scores)
    return corpus, target, selection


# --- Mock LLMProvider ---------------------------------------------------


@dataclass
class _MockProvider:
    """Returns the next canned response per call; records each call."""

    name: str = "mock"
    responses: list[LLMResponse] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)

    def complete(
        self,
        *,
        system: str,
        messages: list[Msg],
        tools: list[Tool] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        self.calls.append(
            {
                "system": system,
                "messages": [m.model_dump() for m in messages],
                "tools": [t.model_dump() for t in tools] if tools else None,
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        )
        if not self.responses:
            raise RuntimeError("mock provider exhausted")
        return self.responses.pop(0)


def _tool_use_resp(payload: dict[str, Any]) -> LLMResponse:
    return LLMResponse(text="", model="mock-model", tool_use=payload)


def _text_only_resp(text: str = "hi") -> LLMResponse:
    return LLMResponse(text=text, model="mock-model", tool_use=None)


# --- Numeric-token helpers (standalone unit tests) ----------------------


def test_extract_numeric_tokens_catches_money_and_percent() -> None:
    assert _extract_numeric_tokens("Saved $2,500,000 in 2023, reducing 50%") >= {
        "$2,500,000",
        "50%",
    }


def test_introduces_new_facts_flags_fabricated_metric() -> None:
    assert _introduces_new_facts(
        source="Reduced latency in the pipeline",
        rewritten="Reduced latency by 50ms across the pipeline",
    )


def test_introduces_new_facts_allows_reorderings() -> None:
    assert not _introduces_new_facts(
        source="Saved $2M by migrating 15 services",
        rewritten="Migrated 15 services, saving $2M in licensing",
    )


# --- Pass A end-to-end (headline + summary) -----------------------------


def test_synthesize_populates_headline_and_summary(tmp_path: Path) -> None:
    _person(tmp_path)
    _org(tmp_path)
    _role(tmp_path, "r")
    _claim(
        tmp_path,
        "c_impact",
        "role",
        "r",
        text="Led a cross-functional migration",
        ctype="impact",
    )

    corpus, target, selection = _build(tmp_path)
    scores = score_claims(corpus, target, now="2025-01")

    provider = _MockProvider(
        responses=[
            _tool_use_resp(
                {
                    "headline": "Senior Engineer ready for distributed systems",
                    "summary": "Led a cross-functional migration. Ships on time.",
                }
            ),
            _tool_use_resp(
                {
                    "bullets": [
                        {
                            "claim_id": "c_impact",
                            "rewritten": "Led a cross-functional migration for platform",
                        },
                    ]
                }
            ),
        ]
    )

    resume = synthesize(corpus, target, selection, scores, provider)

    assert isinstance(resume, RenderedResume)
    assert resume.headline == "Senior Engineer ready for distributed systems"
    assert resume.summary.startswith("Led a cross-functional migration")
    assert resume.person.id == "p"


def test_pass_a_missing_tool_use_raises(tmp_path: Path) -> None:
    _person(tmp_path)
    _org(tmp_path)
    _role(tmp_path, "r")
    _claim(tmp_path, "c", "role", "r", ctype="impact")

    corpus, target, selection = _build(tmp_path)
    scores = score_claims(corpus, target, now="2025-01")

    provider = _MockProvider(responses=[_text_only_resp("no tool use here")])

    with pytest.raises(SynthesisError, match="Pass A"):
        synthesize(corpus, target, selection, scores, provider)


def test_no_summary_candidates_skips_pass_a(tmp_path: Path) -> None:
    """No impact/outcome claims -> summary_claim_ids empty -> no LLM call."""
    _person(tmp_path)
    _org(tmp_path)
    _role(tmp_path, "r")
    _claim(tmp_path, "c_context", "role", "r", ctype="context")

    corpus, target, selection = _build(tmp_path)
    scores = score_claims(corpus, target, now="2025-01")
    assert selection.summary_claim_ids == ()

    provider = _MockProvider(
        responses=[
            _tool_use_resp(
                {
                    "bullets": [
                        {"claim_id": "c_context", "rewritten": "did context stuff"}
                    ]
                }
            )
        ]
    )

    resume = synthesize(corpus, target, selection, scores, provider)

    assert resume.headline is None
    assert resume.summary is None
    # Pass B still ran once for the role
    assert len(provider.calls) == 1


# --- Pass B end-to-end (bullet rewrites) --------------------------------


def test_pass_b_bullets_appear_in_role_section(tmp_path: Path) -> None:
    _person(tmp_path)
    _org(tmp_path)
    _role(tmp_path, "r")
    _claim(tmp_path, "c1", "role", "r", text="did x", ctype="impact")
    _claim(tmp_path, "c2", "role", "r", text="did y", ctype="outcome")

    corpus, target, selection = _build(tmp_path)
    scores = score_claims(corpus, target, now="2025-01")

    provider = _MockProvider(
        responses=[
            _tool_use_resp(
                {"headline": "X", "summary": "Did x and y."},
            ),
            _tool_use_resp(
                {
                    "bullets": [
                        {"claim_id": "c1", "rewritten": "rewrote x cleanly"},
                        {"claim_id": "c2", "rewritten": "rewrote y cleanly"},
                    ]
                }
            ),
        ]
    )

    resume = synthesize(corpus, target, selection, scores, provider)

    role_sections = [s for s in resume.sections if s.name == "role:r"]
    assert len(role_sections) == 1
    assert role_sections[0].kind == "bullets"
    assert role_sections[0].bullets == ["rewrote x cleanly", "rewrote y cleanly"]


def test_pass_b_hallucinated_metric_falls_back_to_source(tmp_path: Path) -> None:
    """LLM invents a '50ms' number not in source -> fallback to original."""
    _person(tmp_path)
    _org(tmp_path)
    _role(tmp_path, "r")
    _claim(
        tmp_path,
        "c1",
        "role",
        "r",
        text="Reduced latency on the ingestion path",
        ctype="impact",
    )

    corpus, target, selection = _build(tmp_path)
    scores = score_claims(corpus, target, now="2025-01")

    provider = _MockProvider(
        responses=[
            _tool_use_resp({"headline": "X", "summary": "did work"}),
            _tool_use_resp(
                {
                    "bullets": [
                        {
                            "claim_id": "c1",
                            "rewritten": (
                                "Reduced ingestion latency by 50ms across the stack"
                            ),
                        }
                    ]
                }
            ),
        ]
    )

    resume = synthesize(corpus, target, selection, scores, provider)

    bullets = next(s.bullets for s in resume.sections if s.name == "role:r")
    assert bullets == ["Reduced latency on the ingestion path"]


def test_pass_b_kept_metric_passes_check(tmp_path: Path) -> None:
    """LLM preserves the source's $2M -> kept verbatim (no fallback)."""
    _person(tmp_path)
    _org(tmp_path)
    _role(tmp_path, "r")
    _claim(
        tmp_path,
        "c1",
        "role",
        "r",
        text="Saved $2M by consolidating vendors",
        ctype="impact",
    )

    corpus, target, selection = _build(tmp_path)
    scores = score_claims(corpus, target, now="2025-01")

    provider = _MockProvider(
        responses=[
            _tool_use_resp({"headline": "X", "summary": "Saved $2M."}),
            _tool_use_resp(
                {
                    "bullets": [
                        {
                            "claim_id": "c1",
                            "rewritten": "Consolidated vendors, saving $2M annually",
                        }
                    ]
                }
            ),
        ]
    )

    resume = synthesize(corpus, target, selection, scores, provider)

    bullets = next(s.bullets for s in resume.sections if s.name == "role:r")
    assert bullets == ["Consolidated vendors, saving $2M annually"]


def test_pass_b_missing_claim_in_response_falls_back(tmp_path: Path) -> None:
    """LLM omits c2 -> c2 falls back to source text."""
    _person(tmp_path)
    _org(tmp_path)
    _role(tmp_path, "r")
    _claim(tmp_path, "c1", "role", "r", text="did x", ctype="impact")
    _claim(tmp_path, "c2", "role", "r", text="did y", ctype="outcome")

    corpus, target, selection = _build(tmp_path)
    scores = score_claims(corpus, target, now="2025-01")

    provider = _MockProvider(
        responses=[
            _tool_use_resp({"headline": "X", "summary": "did x"}),
            _tool_use_resp(
                {
                    "bullets": [
                        {"claim_id": "c1", "rewritten": "cleanly did x"},
                    ]
                }
            ),
        ]
    )

    resume = synthesize(corpus, target, selection, scores, provider)

    bullets = next(s.bullets for s in resume.sections if s.name == "role:r")
    assert "cleanly did x" in bullets
    assert "did y" in bullets


def test_pass_b_provider_error_falls_back_to_source(tmp_path: Path) -> None:
    """A raised exception during Pass B must not lose the role's bullets."""
    _person(tmp_path)
    _org(tmp_path)
    _role(tmp_path, "r")
    _claim(tmp_path, "c1", "role", "r", text="did x", ctype="impact")

    corpus, target, selection = _build(tmp_path)
    scores = score_claims(corpus, target, now="2025-01")

    # Pass A succeeds; Pass B raises on the second call.
    provider = _MockProvider(
        responses=[
            _tool_use_resp({"headline": "X", "summary": "did x"}),
        ]
    )
    resume = synthesize(corpus, target, selection, scores, provider)

    bullets = next(s.bullets for s in resume.sections if s.name == "role:r")
    assert bullets == ["did x"]


def test_role_with_no_claims_has_no_section(tmp_path: Path) -> None:
    _person(tmp_path)
    _org(tmp_path)
    _role(tmp_path, "r_empty", achievement_ids=["a1"])
    _achievement(tmp_path, "a1")
    _role(tmp_path, "r_full")
    _claim(tmp_path, "c", "role", "r_full", ctype="impact")

    corpus, target, selection = _build(tmp_path)
    scores = score_claims(corpus, target, now="2025-01")

    provider = _MockProvider(
        responses=[
            _tool_use_resp({"headline": "X", "summary": "x"}),
            _tool_use_resp({"bullets": [{"claim_id": "c", "rewritten": "rewrote c"}]}),
        ]
    )

    resume = synthesize(corpus, target, selection, scores, provider)

    names = {s.name for s in resume.sections}
    assert names == {"role:r_full"}


# --- RenderedResume assembly --------------------------------------------


def test_rendered_resume_includes_selected_entities(tmp_path: Path) -> None:
    _person(tmp_path)
    _org(tmp_path, "acme")
    _role(tmp_path, "r_acme", org_id="acme", achievement_ids=["a1"])
    _achievement(tmp_path, "a1", role_id="r_acme")
    _write(
        tmp_path / "skills" / "python.yaml",
        "kind: skill\nid: python\nname: Python\ntier: foundational\n",
    )
    _write(
        tmp_path / "education" / "bsc.yaml",
        "kind: education\nid: bsc\ninstitution: Uni\ncredential: BSc CS\n",
    )

    corpus, target, selection = _build(tmp_path)
    scores = score_claims(corpus, target, now="2025-01")

    # No claims -> both passes skipped; provider never called.
    provider = _MockProvider(responses=[])
    resume = synthesize(corpus, target, selection, scores, provider)

    assert resume.person.id == "p"
    assert [r.id for r in resume.roles] == ["r_acme"]
    assert [o.id for o in resume.organizations] == ["acme"]
    assert [a.id for a in resume.achievements] == ["a1"]
    assert [s.id for s in resume.skills] == ["python"]
    assert [e.id for e in resume.education] == ["bsc"]
    # Provider was not called because there's nothing to synthesize.
    assert provider.calls == []


def test_metadata_carries_target_and_counts(tmp_path: Path) -> None:
    _person(tmp_path)
    _org(tmp_path)
    _role(tmp_path, "r")
    _claim(tmp_path, "c", "role", "r", ctype="impact")

    corpus, target, selection = _build(tmp_path)
    scores = score_claims(corpus, target, now="2025-01")

    provider = _MockProvider(
        responses=[
            _tool_use_resp({"headline": "X", "summary": "x"}),
            _tool_use_resp({"bullets": [{"claim_id": "c", "rewritten": "rewrote c"}]}),
        ]
    )

    resume = synthesize(corpus, target, selection, scores, provider)

    assert resume.metadata["target_id"] == "t"
    assert resume.metadata["target_role_title"] == "Senior Engineer"
    assert resume.metadata["selected_roles"] == "1"
    assert resume.metadata["summary_claim_count"] == "1"


# --- Prompt / tool-schema shape -----------------------------------------


def test_pass_a_prompt_includes_target_and_person(tmp_path: Path) -> None:
    _person(tmp_path)
    _org(tmp_path)
    _role(tmp_path, "r")
    _claim(tmp_path, "c", "role", "r", ctype="impact")

    corpus, target, selection = _build(tmp_path)
    scores = score_claims(corpus, target, now="2025-01")

    provider = _MockProvider(
        responses=[
            _tool_use_resp({"headline": "X", "summary": "x"}),
            _tool_use_resp({"bullets": [{"claim_id": "c", "rewritten": "rewrote c"}]}),
        ]
    )

    synthesize(corpus, target, selection, scores, provider)

    pass_a_call = provider.calls[0]
    user_content = pass_a_call["messages"][0]["content"]
    assert "Senior Engineer" in user_content
    assert "Contoso" in user_content
    assert "Pat Q" in user_content
    # Tool-use structured output wired correctly
    assert pass_a_call["tools"] is not None
    assert pass_a_call["tools"][0]["name"] == "emit_headline_and_summary"


def test_pass_b_prompt_includes_role_and_claims(tmp_path: Path) -> None:
    _person(tmp_path)
    _org(tmp_path, "acme")
    _role(tmp_path, "r_acme", org_id="acme")
    _claim(tmp_path, "c", "role", "r_acme", text="specific source text", ctype="impact")

    corpus, target, selection = _build(tmp_path)
    scores = score_claims(corpus, target, now="2025-01")

    provider = _MockProvider(
        responses=[
            _tool_use_resp({"headline": "X", "summary": "x"}),
            _tool_use_resp({"bullets": [{"claim_id": "c", "rewritten": "rewrote"}]}),
        ]
    )

    synthesize(corpus, target, selection, scores, provider)

    pass_b_call = provider.calls[1]
    content = pass_b_call["messages"][0]["content"]
    assert "ACME" in content  # organization name
    assert "specific source text" in content
    assert pass_b_call["tools"][0]["name"] == "emit_bullets"
