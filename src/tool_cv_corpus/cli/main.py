"""CLI entry point.

Exposed as the ``cv-corpus`` console script via the ``[project.scripts]``
entry in pyproject.toml. Each subcommand lives in its own module so
``cv-corpus <command> --help`` stays focused and a new command does not
grow this file.
"""

from __future__ import annotations

import typer

from . import (
    doctor_cmd,
    generate_cmd,
    ingest_cmd,
    init_cmd,
    render_cmd,
    review_cmd,
    schema_cmd,
    validate_cmd,
)

app = typer.Typer(
    name="cv-corpus",
    help=(
        "Compile a graph-of-atoms career corpus into job-targeted CVs, "
        "resumes, and cover letters."
    ),
    no_args_is_help=True,
    add_completion=False,
)

app.command("init")(init_cmd.init)
app.command("ingest")(ingest_cmd.ingest)
app.command("validate")(validate_cmd.validate)
app.command("render")(render_cmd.render)
app.command("generate")(generate_cmd.generate)
app.command("review")(review_cmd.review)
app.command("schema")(schema_cmd.schema)
app.command("doctor")(doctor_cmd.doctor)


if __name__ == "__main__":
    app()
