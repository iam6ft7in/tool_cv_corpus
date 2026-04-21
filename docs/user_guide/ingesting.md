# Ingesting external sources

`cv-corpus ingest` asks each registered ingester whether it
`accepts()` the input, then appends its output to the corpus.

## Built-in ingesters

| Name               | Accepts                                           |
|--------------------|---------------------------------------------------|
| `markdown`         | `*.md` / `*.markdown` with YAML frontmatter       |
| `linkedin_export`  | a LinkedIn Basic or Complete export ZIP           |
| `github_profile`   | a text file or `--username` flag                  |
| `orcid`            | a text file or `--orcid-id` flag with a 19-char ID |

## Command

```bash
cv-corpus ingest path/to/linkedin_export.zip --corpus my_career --dry-run
cv-corpus ingest path/to/linkedin_export.zip --corpus my_career
```

`--dry-run` prints the parsed delta without writing, so you can
eyeball for spurious guesses before they enter the corpus.

## Writing a custom ingester

See [Plugin authoring](../plugin_authoring/index.md) for the
`Ingester` protocol and a minimal example.
