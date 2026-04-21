# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **`cv-corpus generate` is real.** Replaces the v0.1.0 stub with a
  full pipeline: loader → scorer → selector → synthesizer → JSON
  `RenderedResume`. Consumes a `Target` entity ID and tailors every
  section to it.
- **Immutable `Corpus` container** (`generate/loader.py`) with
  deterministic visibility filtering, supersession resolution, and
  convenience views (`skills_by_id`, `roles_chronological()`,
  `claims_for()`).
- **Rule-based claim scorer** (`generate/scoring.py`): five additive
  signals (emphasis-skill overlap, avoid-skill overlap, claim type,
  sourced bonus, recency decay with 36-month half-life). Returns
  `ScoreBreakdown` per claim with per-signal attribution.
- **Target-aware selector** (`generate/selection.py`) with
  per-section budgets, leaf-preferred skill dedup, ancestor-avoid
  cascade, best-effort char-budget trimming.
- **Two-pass LLM synthesis** (`generate/synthesis.py`) using Anthropic
  tool-use for structured output. Pass A emits headline + summary;
  Pass B (one call per role) rewrites bullets. No-new-facts guard
  rejects rewrites that introduce numeric tokens absent from the
  source claim, falling back to original text.
- **`LLMResponse.tool_use`** field for structured-output callers;
  Anthropic provider extracts the first tool-use content block.
- **`CachedLLMProvider`** wraps any provider with the existing
  SQLite `LLMResponseCache`; transparent to callers.
- **CLI flags**: `--target`, `--out`, `--max-visibility`,
  `--dry-run`, `--no-llm`, `--provider`, `--model`, `--no-cache`.
  `--dry-run` prints a Rich manifest of the selection; `--no-llm`
  builds a deterministic `RenderedResume` from raw `Claim.text`.
- **Shared YAML walker** at `io/yaml_loader.py`; both the validator
  and the new loader use it, replacing duplicated `rglob` +
  `safe_load` logic.
- **Docs**: new `docs/user_guide/generating.md` page; architecture
  section extended with a `Generate pipeline` breakdown of all four
  stages.

### Fixed

- `kind: claim` YAML files were being rejected by `Claim.extra =
  "forbid"` because `Claim` has no `kind` field. Both the new loader
  and the validator's `_c07_claim_subjects` now strip the
  discriminator before validating. Latent bug: never triggered
  because the v0.1.0 example corpus ships without any claim files.

### Changed

- `ValidatorRunner._c02_parse_yaml` now delegates to the shared
  `iter_yaml_files` helper. Behavior unchanged; logic deduplicated.

### Removed
