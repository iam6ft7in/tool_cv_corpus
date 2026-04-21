# Schema

The corpus is a graph of 13 entity kinds plus a `Claim` record type
that layers sourced assertions over any subject.

## Entities

| Kind                | Purpose                                           |
|---------------------|---------------------------------------------------|
| `person`            | The subject of the corpus (exactly one in v0.1.0). |
| `organization`      | Employer, client, school, or publishing venue.     |
| `role`              | One tenure at one organization.                    |
| `project`           | An initiative within or across roles.              |
| `achievement`       | A discrete outcome, typically a CV-bullet atom.    |
| `skill`             | Competency, tiered foundational / applied / domain. |
| `education`         | Formal credential or substantial training.         |
| `publication`       | Paper, article, talk, podcast.                     |
| `artifact`          | Linkable deliverable: repo, demo, design doc.      |
| `testimonial`       | Third-party quote.                                 |
| `cover_letter_seed` | Reusable narrative fragment (first person).        |
| `target`            | A specific job application being tailored for.     |
| `source_doc`        | Pointer into the content-addressable source store. |

## Design invariants

1. **Claims over overwrites.** Refined facts append; originals stay
   for audit. The generator scores and picks at render time.
2. **Structured impact.** Metrics are numeric with explicit units,
   not parsed from prose. Renderers format freely.
3. **Three-layer skill taxonomy.** Foundational, applied, domain.
   Flattening hides the signal recruiters key off.
4. **Visibility tiers.** Every entity and claim carries
   `public` / `nda` / `private`; redaction is a render-time filter,
   not a rewrite.
5. **Content-addressable source store.** Ingested binaries live
   outside the repo, keyed by sha256. The corpus references them
   via `SourceDoc` metadata.
6. **Per-entity schema versioning.** Each file carries its own
   `schema_version`, so migrations run file-by-file without a flag
   day.

## Reference

Export JSON Schemas per kind:

```bash
cv-corpus schema --out schemas/
```
