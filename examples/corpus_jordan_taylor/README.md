# Example corpus: Jordan Taylor

Synthetic career data used by tests, docs, and new-user tutorials.

**Everything in this directory is fictional.** Names, companies, dates,
and metrics are made up for illustration; any resemblance to real
people or organizations is coincidental.

## Shape

- 1 `Person` (`jordan_taylor`)
- 2 `Organization` entities (`acme_analytics`, `helioform_labs`)
- 2 `Role` entities (one closed, one ongoing)
- 4 `Achievement` entities with `ImpactMetric` records attached
- 8 `Skill` entities spread across the three taxonomy tiers
  (foundational / applied / domain)
- 1 `Testimonial`
- 1 `Target` (a fictional senior platform role)

## Uses

```bash
uv run cv-corpus validate examples/corpus_jordan_taylor
uv run cv-corpus schema --out schemas/
```

If you add or remove entities, re-run `cv-corpus validate` to keep
the corpus internally consistent. The validator catches broken
cross-references, missing targets for claims, and obvious PII leaks
into public-visibility content.
