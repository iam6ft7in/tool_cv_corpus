# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **`cv-corpus author <corpus>`**: interactive wizard for adding
  entities and Claims. Schema-introspecting prompts cover every field
  on every entity kind (Person, Organization, Role, Project,
  Achievement, Skill, Education, Publication, Artifact, Testimonial,
  CoverLetterSeed, Target, SourceDoc). Foreign-key fields offer a
  picker over existing entities; users can also type a free-form id to
  forward-reference something they have not declared yet (the
  validator's `_c05` check is the right gate for that). Long-form
  fields (`summary`, `description`, `body`, `quote`, ...) accept `:e`
  to open `$EDITOR`. After each entity is written the wizard offers to
  attach a Claim immediately. Tier 1 of the three-tier guided-author
  plan; Tier 2 (LLM paste-and-extract) and Tier 3 (gap detection) will
  build on the same `Prompter` Protocol.
- **`tool_cv_corpus.author`** package exposes the engine for scripting:
  `prompt_for_entity`, `prompt_for_claim`, `Prompter` Protocol,
  `ScriptedPrompter` (test helper), `CorpusState`, `write_entity`,
  `write_claim`, `suggest_entity_id`, `DIRECTORY_BY_KIND`. The CLI
  shell never reaches into schema internals; downstream scripts can
  reuse the same primitives.
- **`LinkedInExportIngester` now reads four more CSVs** from a Complete
  data-export ZIP, closing the gap between the README's plugin
  description and the real ingester surface:
  - `Profile.csv` becomes the `Person` entity (full name, headline,
    geo location, optional Twitter/Websites under `contact`) plus a
    `Claim(type=context, tags=[linkedin, profile_summary])` carrying
    the long-form summary.
  - `Positions.csv` `Description` now emits a
    `Claim(type=context, tags=[linkedin, position_description])` on
    each Role; previously dropped on the floor.
  - `Recommendations_Received.csv` becomes `Testimonial` entities,
    skipping rows whose `Status` is set and not `VISIBLE`.
  - `Endorsement_Received_Info.csv` becomes per-Skill
    `Claim(type=fact, tags=[linkedin, endorsement, date:YYYY-MM-DD])`
    records. Skills referenced by an endorsement but absent from
    `Skills.csv` are auto-emitted at `tier=applied` so the resulting
    Claim has a valid subject under validator check `_c07`.
- **Per-export `SourceDoc`**: every ingested ZIP produces one
  `SourceDoc` whose `sha256` is the digest of the archive bytes,
  `mime_type=application/zip`, and `captured_at` parsed from the
  filename when it matches the standard
  `Complete_LinkedInDataExport_MM-DD-YYYY.zip` shape. Every Claim
  emitted by the ingester references that source by id.

### Fixed

### Changed

### Removed

## [0.2.0] - 2026-04-21

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
