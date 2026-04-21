"""End-to-end tests for ``cv-corpus generate``.

Uses typer's ``CliRunner`` to exercise the real command entry point. All
tests run in ``--no-llm`` or ``--dry-run`` mode so CI does not need an
Anthropic API key.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tool_cv_corpus.cli.main import app
from tool_cv_corpus.render import RenderedResume

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EXAMPLE = REPO_ROOT / "examples" / "corpus_jordan_taylor"

runner = CliRunner()


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _minimal_corpus(root: Path) -> None:
    _write(
        root / "persons" / "p.yaml",
        "kind: person\nid: p\nfull_name: Pat Q\n",
    )
    _write(
        root / "organizations" / "o.yaml",
        "kind: organization\nid: o\nname: O\n",
    )
    _write(
        root / "roles" / "r.yaml",
        "kind: role\nid: r\ntitle: Engineer\norganization_id: o\n"
        "period:\n  start: '2022-01'\n  end: '2024-12'\n",
    )
    _write(
        root / "claims" / "c.yaml",
        "kind: claim\nid: c\nsubject_id: r\nsubject_kind: role\n"
        "type: impact\ntext: Led a tricky migration\n",
    )
    _write(
        root / "targets" / "t.yaml",
        "kind: target\nid: t\nrole_title: Senior Engineer\n"
        "organization_name: Contoso\n",
    )


# --- Happy paths --------------------------------------------------------


def test_no_llm_writes_valid_rendered_resume(tmp_path: Path) -> None:
    _minimal_corpus(tmp_path)
    out = tmp_path / "out.json"

    result = runner.invoke(
        app,
        [
            "generate",
            str(tmp_path),
            "--target",
            "t",
            "--out",
            str(out),
            "--no-llm",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert out.is_file()
    data = json.loads(out.read_text(encoding="utf-8"))
    # Round-trips through the Pydantic model cleanly.
    resume = RenderedResume.model_validate(data)
    assert resume.person.id == "p"
    assert [r.id for r in resume.roles] == ["r"]
    role_sections = [s for s in resume.sections if s.name == "role:r"]
    assert len(role_sections) == 1
    # --no-llm uses raw claim text verbatim.
    assert role_sections[0].bullets == ["Led a tricky migration"]
    # Pass A was skipped; headline/summary remain None.
    assert resume.headline is None
    assert resume.summary is None


def test_dry_run_prints_manifest_and_skips_llm(tmp_path: Path) -> None:
    _minimal_corpus(tmp_path)
    out = tmp_path / "out.json"

    result = runner.invoke(
        app,
        [
            "generate",
            str(tmp_path),
            "--target",
            "t",
            "--out",
            str(out),
            "--dry-run",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "Dry run for target" in result.stdout
    assert "Roles" in result.stdout
    assert not out.exists()  # dry-run never writes.


def test_no_llm_on_example_corpus_succeeds(tmp_path: Path) -> None:
    """The example corpus ships with a Target but no claims; --no-llm
    should still produce a valid RenderedResume."""
    target_yaml = EXAMPLE / "targets" / "principal_eng_foo_tech.yaml"
    assert target_yaml.is_file(), "example corpus missing its target"

    out = tmp_path / "out.json"
    result = runner.invoke(
        app,
        [
            "generate",
            str(EXAMPLE),
            "--target",
            "principal_eng_foo_tech",
            "--out",
            str(out),
            "--no-llm",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert out.is_file()
    resume = RenderedResume.model_validate_json(out.read_text(encoding="utf-8"))
    assert resume.person.full_name == "Jordan Taylor"
    # Example has roles and skills even without claims.
    assert len(resume.roles) >= 1
    assert len(resume.skills) >= 1


# --- Exit-code behavior -------------------------------------------------


def test_missing_corpus_directory_exits_3(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "generate",
            str(tmp_path / "does_not_exist"),
            "--target",
            "t",
            "--out",
            str(tmp_path / "out.json"),
            "--no-llm",
        ],
    )

    assert result.exit_code == 3
    assert "Failed to load corpus" in result.stdout


def test_unknown_target_exits_2(tmp_path: Path) -> None:
    _minimal_corpus(tmp_path)

    result = runner.invoke(
        app,
        [
            "generate",
            str(tmp_path),
            "--target",
            "no_such_target",
            "--out",
            str(tmp_path / "out.json"),
            "--no-llm",
        ],
    )

    assert result.exit_code == 2
    assert "Target 'no_such_target' not found" in result.stdout
    # Lists available target IDs to help the user.
    assert "Available targets: t" in result.stdout


def test_invalid_max_visibility_exits_2(tmp_path: Path) -> None:
    _minimal_corpus(tmp_path)

    result = runner.invoke(
        app,
        [
            "generate",
            str(tmp_path),
            "--target",
            "t",
            "--out",
            str(tmp_path / "out.json"),
            "--max-visibility",
            "secret",
            "--no-llm",
        ],
    )

    assert result.exit_code == 2
    assert "--max-visibility" in result.stdout


def test_unknown_provider_exits_2(tmp_path: Path) -> None:
    _minimal_corpus(tmp_path)

    result = runner.invoke(
        app,
        [
            "generate",
            str(tmp_path),
            "--target",
            "t",
            "--out",
            str(tmp_path / "out.json"),
            "--provider",
            "palantir",
        ],
    )

    assert result.exit_code == 2
    assert "Unknown provider" in result.stdout


# --- Visibility cap plumbing -------------------------------------------


def test_max_visibility_public_redacts_private_entities(tmp_path: Path) -> None:
    _minimal_corpus(tmp_path)
    _write(
        tmp_path / "skills" / "secret.yaml",
        "kind: skill\nid: secret\nname: Secret\ntier: applied\nvisibility: private\n",
    )
    _write(
        tmp_path / "skills" / "public.yaml",
        "kind: skill\nid: pub\nname: Pub\ntier: applied\nvisibility: public\n",
    )

    out = tmp_path / "out.json"
    result = runner.invoke(
        app,
        [
            "generate",
            str(tmp_path),
            "--target",
            "t",
            "--out",
            str(out),
            "--max-visibility",
            "public",
            "--no-llm",
        ],
    )

    assert result.exit_code == 0, result.stdout
    resume = RenderedResume.model_validate_json(out.read_text(encoding="utf-8"))
    ids = {s.id for s in resume.skills}
    assert "secret" not in ids
    assert "pub" in ids


def test_output_parent_directories_are_created(tmp_path: Path) -> None:
    _minimal_corpus(tmp_path)
    out = tmp_path / "deep" / "nested" / "out.json"

    result = runner.invoke(
        app,
        [
            "generate",
            str(tmp_path),
            "--target",
            "t",
            "--out",
            str(out),
            "--no-llm",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert out.is_file()


# --- Sanity: re-exporting through the renderer would work ----------------


def test_rendered_resume_is_renderer_compatible(tmp_path: Path) -> None:
    """The CLI output must deserialize into the exact model renderers
    consume. Guard against accidental field drift."""
    _minimal_corpus(tmp_path)
    out = tmp_path / "out.json"
    runner.invoke(
        app,
        [
            "generate",
            str(tmp_path),
            "--target",
            "t",
            "--out",
            str(out),
            "--no-llm",
        ],
    )

    # RenderedResume(extra='forbid') will raise if the CLI emits an
    # unexpected key; this test pins that contract.
    RenderedResume.model_validate_json(out.read_text(encoding="utf-8"))


@pytest.mark.parametrize("flag", ["--dry-run", "--no-llm"])
def test_offline_flags_do_not_touch_network(tmp_path: Path, flag: str) -> None:
    """Neither flag should need an API key. A missing ANTHROPIC_API_KEY
    would surface as a provider error; we verify by simply running with
    no key in the environment."""
    _minimal_corpus(tmp_path)
    out = tmp_path / "out.json"

    result = runner.invoke(
        app,
        [
            "generate",
            str(tmp_path),
            "--target",
            "t",
            "--out",
            str(out),
            flag,
        ],
        env={"ANTHROPIC_API_KEY": ""},
    )

    assert result.exit_code == 0, result.stdout
