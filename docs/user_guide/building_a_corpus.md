# Building a corpus

## The shape

Each entity is a YAML file (or Markdown with YAML frontmatter) under
the matching per-kind directory:

```
corpus/
  persons/jordan_taylor.yaml
  organizations/acme_analytics.yaml
  roles/senior_swe_acme_2021.yaml
  achievements/launched_metered_billing.yaml
  skills/python.yaml
```

Every file carries a `kind:` discriminator, a stable `id:`, and a
`schema_version:` that defaults to the current release.

## Claims over overwrites

When a fact is refined, append a `Claim` rather than mutating the
underlying entity. The generator picks the best-scored claim at
render time; older claims remain for audit.

```yaml
kind: claim
id: claim_arr_refined
subject_id: ach_launched_metered_billing
subject_kind: achievement
type: impact
text: "Net new ARR attributable to metered billing: ~$4.2M in Q4 2022."
sources: [perf_review_2022_q4]
```

## Visibility and redaction

Every entity has a `visibility:` of `public`, `nda`, or `private`.
Redaction profiles filter at render time so you can keep one corpus
rather than one-per-recipient. The default `public` profile drops
anything above `public` before the rendered intermediate is handed
to a renderer.

## External sources

See [Ingesting external sources](ingesting.md) for pulling from
LinkedIn exports, GitHub, and ORCID.
