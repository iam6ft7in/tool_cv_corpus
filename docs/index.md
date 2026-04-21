# tool_cv_corpus

A schema-driven, LLM-assisted engine that compiles a
**graph-of-atoms** career corpus into job-targeted CVs, resumes, and
cover letters.

## Why

Most resume tooling treats a CV as a document you edit directly. That
makes every new target a rewrite, loses the sourcing behind each
bullet, and mixes one-off prose into data you'd otherwise want to
re-use. `tool_cv_corpus` inverts the model:

1. The **corpus** is your structured, sourced career data: roles,
   organizations, achievements, skills, testimonials, and the
   provenance of every claim.
2. A **target** is a specific job posting you are applying to.
3. The engine **resolves** the corpus against the target, scoring
   claims by fit, applying visibility and redaction rules, and emits
   a format-agnostic `RenderedResume`.
4. Pluggable **renderers** turn that intermediate into PDF (Typst),
   JSON Resume, DOCX, or HTML.

## Quick links

- [Getting started](user_guide/getting_started.md)
- [Plugin authoring](plugin_authoring/index.md)
- [Schema reference](architecture/schema.md)
- [Pipeline overview](architecture/pipeline.md)

## Status

Version 0.1.0 ships the schema, CLI surface, validator, and the
default renderer/ingester/LLM plugin set. The claim-scoring and
target-aware generation phases are stubs; contributions welcome via
the [plugin authoring guide](plugin_authoring/index.md).
