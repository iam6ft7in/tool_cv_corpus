"""Typst renderer.

Typst is a modern typesetting system that compiles plain text to PDF.
It is the default "nice PDF" path for this tool because:

- the source is diff-friendly (unlike LaTeX fragments or Word XML),
- compile is fast enough to be part of a CI preview,
- templates are easy to fork and customise without learning a dense DSL.

Runtime behaviour:

1. We always write ``resume.json`` next to the template so the .typ file
   can ``json("resume.json")`` to read structured data.
2. If the ``typst`` binary is on ``PATH`` we compile to PDF. Otherwise
   we return the .typ path and warn: the user can compile later or
   install Typst. This keeps the tool usable on systems where Typst is
   not installed (GitHub Codespaces out of the box, locked-down corp
   laptops, CI without Typst).
"""

from __future__ import annotations

import shutil
import subprocess
from importlib import resources
from pathlib import Path
from typing import ClassVar

from .base import RenderedResume

_DEFAULT_TEMPLATE_NAME = "default.typ"


class TypstRenderer:
    """Render a RenderedResume as Typst source, optionally compiling to PDF."""

    name: ClassVar[str] = "typst"
    extensions: ClassVar[tuple[str, ...]] = (".pdf", ".typ")

    def __init__(self, template_path: Path | None = None) -> None:
        self._template_override = template_path

    def render(self, resume: RenderedResume, out_path: Path) -> Path:
        out_dir = out_path.parent if out_path.suffix else out_path
        out_dir.mkdir(parents=True, exist_ok=True)
        resume_json = out_dir / "resume.json"
        resume_json.write_text(
            resume.model_dump_json(indent=2),
            encoding="utf-8",
        )
        typ_source = out_dir / "resume.typ"
        typ_source.write_text(self._template(), encoding="utf-8")

        typst_bin = shutil.which("typst")
        if typst_bin is None:
            return typ_source

        pdf_out = out_path if out_path.suffix == ".pdf" else out_dir / "resume.pdf"
        subprocess.run(
            [typst_bin, "compile", str(typ_source), str(pdf_out)],
            check=True,
            cwd=out_dir,
        )
        return pdf_out

    def _template(self) -> str:
        if self._template_override is not None:
            return self._template_override.read_text(encoding="utf-8")
        return (
            resources.files("tool_cv_corpus.render.templates.typst")
            .joinpath(_DEFAULT_TEMPLATE_NAME)
            .read_text(encoding="utf-8")
        )
