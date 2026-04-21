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
