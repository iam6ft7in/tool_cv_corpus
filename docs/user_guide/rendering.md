# Rendering

The engine produces a format-agnostic `RenderedResume` which
pluggable **renderers** turn into bytes.

## Default renderers

| Name          | Output  | Extra install       |
|---------------|---------|---------------------|
| `typst`       | PDF     | `typst` on PATH     |
| `json_resume` | JSON    | built in            |
| `html`        | HTML    | built in            |
| `docx`        | DOCX    | `[docx]` extra      |

## Command

```bash
cv-corpus render output/rendered_resume.json \
  --format typst \
  --out output/resume
```

`rendered_resume.json` is produced by `cv-corpus generate` (or
hand-crafted if you prefer to drive the engine from a script).

If the selected renderer's suffix is missing from `--out`, the
renderer picks one from its registered `extensions` tuple.

## Typst specifics

The bundled template is intentionally plain. Fork it, point the
renderer at your copy with `--template`, and re-render; no code
changes required.

If `typst` is not on `PATH` the renderer stops after writing
`resume.typ` and `resume.json` next to your output path, so you can
compile later on a machine that has it.
