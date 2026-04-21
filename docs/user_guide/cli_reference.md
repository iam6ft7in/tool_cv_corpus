# CLI reference

All commands are subcommands of `cv-corpus`. Run `cv-corpus --help`
for the live list, or `cv-corpus <command> --help` for any one.

## Commands

| Command    | Purpose                                                             |
|------------|---------------------------------------------------------------------|
| `init`     | Scaffold a new corpus directory from the bundled skeleton.          |
| `ingest`   | Pull an external source into the corpus (auto-detects ingester).    |
| `validate` | Run 11 ordered checks on a corpus directory.                        |
| `render`   | Format a `RenderedResume` JSON with a registered renderer.          |
| `generate` | Produce a target-tailored `RenderedResume` (v0.2).                  |
| `review`   | Pretty-print a `RenderedResume` for a quick read.                   |
| `schema`   | Dump pydantic JSON Schemas per entity kind.                         |
| `doctor`   | Diagnose the install: paths, LLM settings, discovered plugins.      |

## Exit codes

| Code | Meaning                                                            |
|-----:|--------------------------------------------------------------------|
|    0 | Success. Warnings may be present; `--strict` promotes them.        |
|    1 | Errors. The operation did not complete.                            |
|    2 | Bad invocation. Missing file, unknown plugin, etc.                 |
|    3 | Invalid corpus structure that prevented the run from starting.    |

## Environment

| Variable                   | Effect                                        |
|----------------------------|-----------------------------------------------|
| `CV_CORPUS_SOURCE_STORE`   | Override the CAS root (default: platformdirs). |
| `CV_CORPUS_MODEL`          | Override the default LLM model.                |
| `ANTHROPIC_API_KEY`        | Picked up by the Anthropic provider.           |
| `OPENAI_API_KEY`           | Picked up by the OpenAI provider (stub).       |
