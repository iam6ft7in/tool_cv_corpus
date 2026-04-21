# Generating a targeted resume

`cv-corpus generate` compiles a validated corpus into a
`RenderedResume` tailored to one `Target` entity. Output is JSON; any
registered renderer (`typst`, `json_resume`, `docx`, `html`) can turn
that JSON into a final document via `cv-corpus render`.

## The four-stage pipeline

```
corpus (YAML)                  Target (YAML)
      |                              |
      v                              v
 +----------+     +---------+    +----------+    +-----------+    +----------------+
 |  loader  | --> | scorer  |--->| selector |--->| synthesis |--->| RenderedResume |
 +----------+     +---------+    +----------+    +-----------+    +----------------+
   resolves         ranks           picks          LLM rewrites       JSON on disk
   and              every           per-section    (or raw text
   redacts          claim           what fits      under --no-llm)
```

Each stage is deterministic for fixed inputs. The synthesis stage is
the only place an LLM is allowed to invent prose.

1. **Loader** (`generate/loader.py`) parses the corpus, applies
   migrations, validates against the Pydantic schema, enforces exactly
   one `Person`, drops claims superseded by an active successor, and
   applies the visibility cap. Returns an immutable `Corpus`.
2. **Scorer** (`generate/scoring.py`) scores each claim on five
   signals: emphasis-skill overlap, avoid-skill overlap, claim type,
   sourced-ness, and recency. Each claim gets a `ScoreBreakdown` with
   per-signal contributions for future `--explain` views.
3. **Selector** (`generate/selection.py`) picks the subset under
   per-section budgets: roles chronologically, top achievements per
   role, leaf-preferred skills (drops the parent when a descendant
   qualifies), summary claims by type, per-subject claims capped.
4. **Synthesis** (`generate/synthesis.py`) runs two LLM calls:
   Pass A for headline+summary, Pass B per role for bullet rewrites.
   Both use Anthropic tool-use with Pydantic-derived `input_schema`
   for reliable structured output. A "no new facts" guard rejects any
   rewritten bullet that introduces a numeric token absent from the
   source claim; those fall back to the original `Claim.text`.

## Quick start

Assuming `my_corpus/targets/senior_eng_foo_corp.yaml` exists and the
rest of the corpus passes `cv-corpus validate`:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
cv-corpus generate my_corpus \
  --target senior_eng_foo_corp \
  --out output/senior_eng_foo_corp.json
```

Follow with a renderer:

```bash
cv-corpus render output/senior_eng_foo_corp.json \
  --renderer typst \
  --out output/senior_eng_foo_corp.pdf
```

## Flags

| Flag | Default | Purpose |
|------|---------|---------|
| `--target`, `-t` | required | ID of the `Target` entity to tailor towards. |
| `--out`, `-o` | `output/rendered_resume.json` | Where to write the `RenderedResume` JSON. |
| `--max-visibility` | `private` | Redaction cap. `public` drops `nda` and `private`; `nda` drops `private`; `private` keeps all. |
| `--dry-run` | `false` | Stop after selection. Prints the manifest; no LLM call, no file write. |
| `--no-llm` | `false` | Skip synthesis. Build `RenderedResume` from raw `Claim.text`. Deterministic and free. |
| `--provider` | `anthropic` | LLM provider. v0.2 supports `anthropic`; more via entry points in later releases. |
| `--model` | provider default | Model ID override. Anthropic default is `claude-sonnet-4-6`. |
| `--no-cache` | `false` | Skip the SQLite LLM response cache for this run. |

## Exit codes

| Code | Meaning |
|-----:|---------|
| 0 | `RenderedResume` written, or `--dry-run` manifest printed. |
| 1 | Synthesis error (e.g., LLM did not return a tool-use call). |
| 2 | Bad invocation: unknown target, unknown provider, bad `--max-visibility`. |
| 3 | Corpus failed to load. Run `cv-corpus validate` for detail. |

## The two offline modes

### `--dry-run`: inspect selection, no synthesis

`--dry-run` stops after the selector and prints a Rich manifest:
roles chosen (chronologically), achievements per role (best-first by
score), skills (after leaf preference), summary claims with scores,
and per-subject claim ranking. Use this to:

- Catch an over-aggressive `avoid_skill_ids` entry that is pruning
  relevant claims.
- Verify leaf-preference picked `django` instead of `python` when you
  expected both.
- See which summary claims will anchor the resume before paying for
  an LLM call.

### `--no-llm`: deterministic offline build

`--no-llm` skips Pass A and Pass B entirely. `headline` and `summary`
are left `null`; per-role bullets come from the raw `Claim.text` in
selection order. Useful for:

- CI jobs that must not depend on an API key or network.
- Generating a "reference" resume against which LLM-rewritten output
  can be diffed.
- Iterating on the selector or scorer without per-iteration LLM cost.

## Caching

LLM calls go through `CachedLLMProvider`, a write-through wrapper over
a SQLite file at `platformdirs.user_cache_dir("tool_cv_corpus") /
"llm_cache.sqlite"`. Cache keys are a sha256 of the full request, so:

- Changing `--model` busts only the affected entries.
- Editing one role's claim re-prices only that role's Pass B; other
  roles still hit cache.
- `--no-cache` disables the wrapper; useful while iterating on
  prompts.

## Target shape reminder

A `Target` is just another corpus entity. Minimum viable:

```yaml
kind: target
id: senior_eng_foo_corp
role_title: Senior Engineer
organization_name: Foo Corp
emphasis_skill_ids:
  - python
  - distributed_systems
avoid_skill_ids: []
requirements:
  - "5+ years distributed systems"
  - "Python or Rust"
job_posting_url: https://jobs.example.com/123
```

`emphasis_skill_ids` bias scoring upward (direct match beats ancestor
match); `avoid_skill_ids` push claims toward the floor and exclude
matching skills from the rendered skill list. `requirements` is
free-form text surfaced to the LLM in Pass A and Pass B prompts; the
selector does not score against it.

## No-new-facts guard

Pass B rewrites are checked for numeric tokens (dollar amounts,
percentages, plain integers) that do not appear in the source claim.
If the LLM returns `"Reduced ingestion latency by 50ms"` for a source
that reads `"Reduced ingestion latency"`, the rewrite is rejected and
the original text is emitted instead. Reorderings and synonyms pass;
only fabricated metrics trigger a fallback. Named-entity and
proper-noun checks are a future enhancement.
