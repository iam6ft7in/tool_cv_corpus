# Contributing

Thank you for contributing to tool_cv_corpus. Please read this guide before opening
a pull request.

---

## Branch Naming

All branches use one of six prefixes followed by a slash and a snake_case descriptor.
Branch names are always lowercase with underscores — no hyphens in the descriptor.

| Prefix | Purpose | Example |
|--------|---------|---------|
| `feature/` | New functionality | `feature/add_telemetry_logging` |
| `fix/` | Bug fixes | `fix/correct_baud_rate_calc` |
| `docs/` | Documentation only | `docs/expand_installation_guide` |
| `chore/` | Maintenance, dependencies | `chore/update_dependencies` |
| `refactor/` | Code restructuring (no behavior change) | `refactor/split_parser_module` |
| `test/` | Tests only | `test/add_edge_case_coverage` |

---

## Conventional Commits

All commits must follow [Conventional Commits](https://www.conventionalcommits.org/)
format:

```
type(scope): description
```

- Lowercase imperative mood description, no trailing period.
- Scope is optional but encouraged (e.g., module name, subsystem).

### Commit Types

| Type | Description | Example |
|------|-------------|---------|
| `feat` | New feature | `feat(parser): add NMEA sentence support` |
| `fix` | Bug fix | `fix(pwm): correct duty cycle overflow` |
| `docs` | Documentation only | `docs(readme): add wiring diagram` |
| `style` | Formatting, whitespace | `style: apply ruff formatting` |
| `refactor` | Restructuring without behavior change | `refactor(pid): extract gain helpers` |
| `perf` | Performance improvement | `perf(isr): reduce interrupt latency` |
| `test` | Adding or correcting tests | `test(parser): cover empty packet case` |
| `chore` | Maintenance, tooling | `chore: bump avr-gcc to 13.2` |
| `ci` | CI/CD pipeline changes | `ci: add shellcheck to workflow` |
| `revert` | Reverting a previous commit | `revert: revert feat(parser) from abc123` |

### Signing

All commits must be SSH-signed. Configure signing once:

```bash
git config --global gpg.format ssh
git config --global user.signingkey ~/.ssh/id_ed25519.pub
git config --global commit.gpgsign true
git config --global tag.gpgsign true
```

The "Verified" badge must appear on GitHub for every commit in a PR.

---

## Development Workflow

1. **Fork** the repository (external contributors) or create a branch directly
   (team members with write access).
2. **Branch** from `main` using the naming convention above:
   ```bash
   git checkout -b feature/your_feature_name
   ```
3. **Commit** early and often. Each commit should be a logical unit of work with
   a Conventional Commits message.
4. **Push** your branch and open a Pull Request against `main`.
5. **Squash merge** is the standard merge strategy — the PR title becomes the
   squash commit message, so make it a valid Conventional Commits line.

Never commit directly to `main`.

---

## Pull Request Process

Before marking your PR ready for review, confirm:

- [ ] All commits are SSH-signed (Verified badge on GitHub)
- [ ] Commit messages follow Conventional Commits format
- [ ] No secrets, credentials, or API keys are included
- [ ] `CHANGELOG.md` updated under `[Unreleased]` for `feat` and `fix` changes
- [ ] Documentation updated if the public interface changed
- [ ] Branch is up to date with `main` (rebase or merge)
- [ ] CI checks pass

Fill out the pull request template completely. PRs with no description will be
returned for revision.

---

## Platform Code Style Standards

### Python
- Formatter: `ruff format` (replaces Black)
- Linter: `ruff check` (replaces Flake8/isort/pyupgrade)
- Type hints required on all public functions and methods
- Tests: `pytest` via `uv run pytest`
- Package management: `uv` only (no pip, pipenv, or poetry)
- Minimum Python version: 3.11

### PowerShell
- Linter: `Invoke-ScriptAnalyzer -Path . -Recurse` — zero warnings/errors
- Tests: Pester (`Invoke-Pester`)
- Target: PowerShell 7+ (pwsh) only — no Windows PowerShell 5.x compatibility
- Use approved verbs; all functions must have comment-based help blocks
- `${variable}` curly brace syntax required

### bash/zsh
- Linter: `shellcheck` — zero warnings/errors
- Tests: BATS (`bats tests/`)
- `#!/usr/bin/env bash` shebang on all scripts
- `set -euo pipefail` at the top of every script
- `${variable}` curly brace syntax required

### NASM Assembly (x86-64)
- NASM syntax only (not GAS/AT&T)
- Every non-obvious instruction or block must have a comment explaining intent
- Section layout: `.data`, `.bss`, `.text` in that order
- Labels in snake_case; constants in UPPER_SNAKE_CASE
- Tested in x64dbg on Windows

### ArduPilot / Arduino
- Follows ArduPilot coding conventions where applicable
- No `delay()` in production code — use non-blocking state machines
- All parameters must be documented (name, range, units, description)
- Mission scripts tested in SITL before flight testing
- Firmware must compile without warnings

### VBScript / WSH
- Files encoded in UTF-8 with BOM (required for WSH compatibility)
- `Option Explicit` at the top of every script — no exceptions
- Error handling with `On Error GoTo 0` / `On Error Resume Next` must be
  scoped and explicit, never left open
- Constants in UPPER_SNAKE_CASE; variables in camelCase

### Makefile
- Tab indentation (not spaces) — EditorConfig enforces this
- Each target must have a `.PHONY` declaration if it does not produce a file
- Variables in UPPER_SNAKE_CASE
- Include a `help` target as the default target

---

## Code Review Process

Reviews use a three-tier severity system. Every comment explains WHY, not just WHAT.

### Critical
Must be resolved before the PR is merged. Covers correctness bugs, security
issues, and violations of mandatory conventions.

### Warning
Should be resolved. If intentionally skipped, add a comment to the PR explaining
the decision. Covers suboptimal patterns and missing error handling.

### Suggestion
Optional improvement with a stated rationale. Author decides whether to act on it.
No explanation needed if skipped.

---

## Getting Help

- Open a [Discussion](../../discussions) for questions about design or approach.
- Open an [Issue](../../issues/new/choose) for bugs or feature requests.
- For security concerns, see [SECURITY.md](SECURITY.md) — do not open a public issue.
