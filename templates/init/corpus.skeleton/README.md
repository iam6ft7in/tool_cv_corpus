# Corpus

This is a `tool_cv_corpus` career corpus.

Each entity lives in its own YAML or Markdown file under one of the
per-kind subdirectories below. Edit the files by hand, or use
`cv-corpus ingest` to append from an external source (LinkedIn export,
GitHub profile, ORCID record, local Markdown).

## Layout

```
corpus/
  persons/           # 1 file, describing you
  organizations/     # employers, clients, schools, publishers
  roles/             # each tenure at an organization
  projects/          # initiatives within or across roles (optional)
  achievements/      # outcomes, with ImpactMetric records attached
  skills/            # tiered competencies (foundational / applied / domain)
  educations/        # formal credentials
  publications/      # papers, articles, talks, podcasts
  artifacts/         # linkable repos, demos, design docs
  testimonials/      # third-party quotes
  cover_letter_seeds/ # reusable narrative fragments
  targets/           # specific job applications to tailor towards
  source_docs/       # pointers into the content-addressable source store
  claims/            # sourced assertions layered over entities
```

Not every directory needs to be populated. A useful first corpus is
typically one `Person`, one or two `Role`s, and five to ten
`Achievement`s.

## Validate

```bash
uv run cv-corpus validate .
```
