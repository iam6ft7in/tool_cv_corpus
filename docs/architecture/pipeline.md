# Pipeline

```
                 +-------------+
       Markdown  |             |
       LinkedIn  |  ingesters  +--------+
       GitHub    |             |        |
       ORCID     +-------------+        v
                                    +--------+
                                    | corpus | (graph of atoms on disk)
                                    +---+----+
                                        |
                                        v
                                    +---------+
                                    | loader  |---> resolved entity graph
                                    +---+-----+
                                        |
                                        v
                                +----------------+
                                | generator +    |
                                | LLM cache      |---> RenderedResume (intermediate)
                                +-------+--------+
                                        |
                +-----------+-----------+-----------+-----------+
                v           v           v           v           v
           +----------+ +------+  +------+ +----------+   +-------+
           |  typst   | | json | | docx | |   html   |   |  ...  |
           | (-> PDF) | |Resume| |      | |          |   |       |
           +----------+ +------+  +------+ +----------+   +-------+
                          renderers (format-specific)
```

## Phase boundaries

- **Ingest** turns external sources into corpus deltas. It never
  mutates the corpus in place; a merge step is separate.
- **Validate** runs 11 ordered checks on the corpus. Earlier checks
  are preconditions of later ones.
- **Generate** loads the corpus, scores claims against a target,
  applies visibility / redaction, and emits a `RenderedResume`.
  Prompt caching is applied at the LLM boundary via the SQLite cache.
- **Render** is a pure function of the `RenderedResume`. Renderers
  never reach back into the corpus graph.

## Generate pipeline (v0.2)

`cv-corpus generate` is four substages behind a single CLI surface.
Each substage returns an immutable value the next stage reads; there
is no shared mutable state, so tests can swap any one stage for a
fixture without faking the others.

```
load_corpus  ─►  score_claims  ─►  select  ─►  synthesize  ─►  RenderedResume
```

### 1. Loader (`tool_cv_corpus.generate.loader`)

`load_corpus(root, *, max_visibility)` walks the corpus, parses every
YAML, applies schema migrations, validates against `AnyEntity` and
`Claim`, enforces exactly one `Person`, applies the visibility cap,
and drops claims superseded by an active successor. Returns an
immutable `Corpus` (`MappingProxyType` over entities and
`tuple[Claim, ...]` per subject) so downstream stages can memoize
against it safely.

- **Strict vs permissive**: the loader raises `CorpusLoadError` on
  the first parse or schema failure. The validator (`cv-corpus
  validate`) is the permissive sibling — it accumulates every error
  for a single report. Callers facing bad input are expected to fix
  it via the validator before `generate` can run.

### 2. Scorer (`tool_cv_corpus.generate.scoring`)

`score_claims(corpus, target, weights, now)` returns
`dict[str, ScoreBreakdown]`. Five additive signals, each independently
weighted and each skippable via a zero weight:

| Signal | Default | What it measures |
|---|---|---|
| `emphasis_skill_overlap` | +3.0 per match | subject's skills (expanded up `parent_id`) intersect `Target.emphasis_skill_ids` |
| `avoid_skill_overlap` | -5.0 per match | same, for `avoid_skill_ids`. Stronger than one emphasis match by design |
| `claim_type` | impact=1.0 ... context=0.1 | per-type preference |
| `sourced` | +0.5 | claim has at least one `SourceDoc` reference |
| `recency` | peak 1.0, 36-month half-life | age of subject; open-ended periods resolve to now |

`ScoreBreakdown` carries both `total` and the per-signal `components`
so a future `--explain` view can surface attribution.

### 3. Selector (`tool_cv_corpus.generate.selection`)

`select(corpus, target, scores, budget)` returns a `Selection` of
IDs only. The `Corpus` stays the source of truth for bodies, which
means a selection bug can never silently rewrite a record.

Rules:

- Roles chronologically, newest first, capped by `max_roles`.
- Achievements per role ranked by best claim-score on that
  achievement, capped by `max_achievements_per_role`.
- Skills ranked by direct > ancestor emphasis; avoid-matches and
  ancestor-avoid matches excluded; when both a skill and one of its
  ancestors qualify, the leaf wins.
- Summary claims filtered to `impact` or `outcome`, ranked across all
  subjects, capped by `max_summary_claims`.
- Per-subject claims: top-k by score for every selected subject.
- Char budget: a best-effort trim drops lowest-scoring per-subject
  claims first, then summary claims last, until the total fits
  `total_claim_char_limit`.

### 4. Synthesis (`tool_cv_corpus.generate.synthesis`)

Two LLM passes via Anthropic tool-use:

- **Pass A** (one call): emits `headline` + `summary` via an
  `emit_headline_and_summary` tool whose `input_schema` is derived
  from a `PassAOutput` Pydantic model.
- **Pass B** (one call per role): emits rewritten bullets per source
  claim via `emit_bullets`. Per-role granularity keeps the cache
  useful: editing one role does not re-price the others.

The **no-new-facts guard** checks every rewritten bullet for numeric
tokens absent from the source; offenders fall back to the original
`Claim.text`. Pass A failures raise `SynthesisError`; Pass B failures
fall back silently so one flaky call never erases an entire role.

`--no-llm` swaps synthesis for `synthesize_no_llm`, which reuses the
same assembler but draws bullets from raw `Claim.text`. `--dry-run`
stops before this stage entirely.

### Caching

`CachedLLMProvider` wraps any `LLMProvider` with the SQLite cache at
`cache_dir() / "llm_cache.sqlite"`. Keys are sha256 of the full
request; changing a single prompt word cleanly busts only the
affected entries.
