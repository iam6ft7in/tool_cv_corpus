# Getting started

## Install

```bash
uv add tool-cv-corpus              # runtime only
uv add "tool-cv-corpus[all]"       # include DOCX, PDF extraction, Jinja
```

Or with `pip`:

```bash
pip install tool-cv-corpus
```

## Verify

```bash
cv-corpus doctor
```

`doctor` prints the resolved paths, the model selected via
`CV_CORPUS_MODEL`, and every discovered plugin with its import status.
If a plugin shows `import failed`, reinstall the extra that provides
it.

## Create a corpus

```bash
cv-corpus init my_career
cd my_career
```

The new directory is a tree of per-kind subdirectories (`persons/`,
`roles/`, `achievements/`, ...). Edit the seeded `_replace_me.yaml`
and validate as you go:

```bash
cv-corpus validate .
```

## Try the example

```bash
cv-corpus validate examples/corpus_jordan_taylor
```

The Jordan Taylor corpus ships with 19 synthetic entities you can
point the renderer at while you shape your own data.
