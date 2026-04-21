# Plugin Authoring

`tool_cv_corpus` discovers plugins through
[Python entry points](https://packaging.python.org/en/latest/specifications/entry-points/).
Three plugin kinds are supported:

| Entry-point group                  | Protocol                                           | Purpose                                              |
|------------------------------------|----------------------------------------------------|------------------------------------------------------|
| `tool_cv_corpus.renderers`         | `tool_cv_corpus.render.base.Renderer`              | Format a `RenderedResume` as PDF, JSON, HTML, DOCX, ... |
| `tool_cv_corpus.ingesters`         | `tool_cv_corpus.ingest.base.Ingester`              | Turn an external source into corpus deltas           |
| `tool_cv_corpus.llm_providers`     | `tool_cv_corpus.generate.llm.base.LLMProvider`     | Adapt a vendor's LLM API to the internal `complete()` shape |

## Registering a plugin

In your package's `pyproject.toml`:

```toml
[project.entry-points."tool_cv_corpus.renderers"]
my_format = "my_package.my_module:MyRenderer"
```

The class must conform to the protocol listed above. Protocols are
`@runtime_checkable` so the loader verifies shape on discovery and
fails fast with a clear error rather than at first call.

## Renderer contract

```python
from pathlib import Path
from tool_cv_corpus.render import RenderedResume, Renderer


class MyRenderer:
    name = "my_format"
    extensions = (".mfr",)

    def render(self, resume: RenderedResume, out_path: Path) -> Path:
        out_path = out_path.with_suffix(self.extensions[0])
        out_path.write_text(resume.model_dump_json(indent=2), encoding="utf-8")
        return out_path
```

Invariants:

1. Renderers are pure functions of `RenderedResume`. Do not reach back
   into the corpus graph; if a needed field is missing, open an issue
   to extend the intermediate so every renderer benefits.
2. Write the result to `out_path` (adjust suffix if needed) and return
   the final path. Do not overwrite unrelated files.
3. Use ASCII-safe filenames by default; callers can override.

## Ingester contract

```python
from pathlib import Path
from tool_cv_corpus.ingest import Ingester, IngestResult


class MyIngester:
    name = "my_source"

    def accepts(self, src: Path) -> bool:
        return src.suffix == ".mine"

    def ingest(self, src: Path) -> IngestResult:
        return IngestResult(entities=[], claims=[], sources=[])
```

Invariants:

1. `accepts()` is cheap: extension or magic-byte check only.
2. `ingest()` is idempotent on the same bytes.
3. Emit warnings for partial data; raise only on unrecoverable errors.

## LLM provider contract

```python
from tool_cv_corpus.generate.llm import LLMProvider, LLMResponse, Msg, Tool


class MyProvider:
    name = "my_vendor"

    def complete(
        self,
        *,
        system: str,
        messages: list[Msg],
        tools: list[Tool] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        ...
```

Invariants:

1. Normalise vendor errors into Python exceptions with actionable
   messages; do not leak HTTP response bodies verbatim.
2. Return a populated `usage` dict when the vendor exposes token counts;
   omit buckets rather than inventing zeros.
3. Do not set `cache_hit=True`; the cache owns that flag.

## Testing your plugin

Install your package in editable mode alongside `tool_cv_corpus`:

```bash
uv pip install -e .
uv run cv-corpus doctor
```

`cv-corpus doctor` lists discovered plugins per entry-point group and
flags any that fail protocol conformance.
