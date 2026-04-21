# AI Agent Guidelines

> This file is read by all AI tools (Claude, Copilot, Cursor, etc.) operating in this repository.
> It defines universal rules that apply regardless of which AI assistant is being used.
> Platform-specific rules are added via CLAUDE.md imports.

---

## Universal Coding Standards

### Variable Syntax
- Always use `${variable}` curly brace syntax where the language supports it.
  - Applies to: bash/zsh, PowerShell, Perl, Makefile
  - Rationale: curly braces make variable boundaries unambiguous and prevent subtle
    expansion bugs (e.g., `${var}able` vs `$variable`)

### Secrets and Credentials
- Never commit secrets, credentials, API keys, tokens, or passwords to the repository.
- Use `.env` files (gitignored) or a secrets manager for sensitive values.
- If a secret is accidentally committed, treat it as compromised immediately — rotate it.

### File Editing
- Always read a file before editing it.
- Never overwrite a file based on assumptions about its contents.

### Branch Protection
- Never commit directly to the `main` branch.
- All changes go through a feature branch and pull request.

### Branch Naming (Feature Branch Workflow)
All branch names use one of six prefixes followed by a slash and a snake_case descriptor:

| Prefix | Purpose | Example |
|--------|---------|---------|
| `feature/` | New functionality | `feature/add_servo_control` |
| `fix/` | Bug fixes | `fix/correct_pwm_timing` |
| `docs/` | Documentation only | `docs/update_wiring_guide` |
| `chore/` | Maintenance, dependencies | `chore/bump_avr_toolchain` |
| `refactor/` | Code restructuring (no behavior change) | `refactor/extract_pid_module` |
| `test/` | Tests only | `test/add_unit_tests_for_parser` |

Branch names must be in snake_case (lowercase, underscores, no hyphens in the descriptor).

### Line Length
- Maximum 88 characters per line.
- This applies to code, comments, and documentation prose where technically feasible.
- Exception: URLs and machine-generated content may exceed this limit.

### Language
- Use American English in all documentation, comments, commit messages, and variable names.
  - Correct: "color", "initialize", "behavior"
  - Incorrect: "colour", "initialise", "behaviour"

---

## Commit Standards

### Format
All commits must follow [Conventional Commits](https://www.conventionalcommits.org/) format:

```
type(scope): description

[optional body]

[optional footer(s)]
```

- The description is lowercase, imperative mood, no trailing period.
- The scope is optional but encouraged for larger projects.

### Commit Types

| Type | When to Use |
|------|-------------|
| `feat` | A new feature |
| `fix` | A bug fix |
| `docs` | Documentation changes only |
| `style` | Formatting, whitespace — no logic change |
| `refactor` | Code restructuring without behavior change |
| `perf` | Performance improvement |
| `test` | Adding or correcting tests |
| `chore` | Maintenance, dependency updates, tooling |
| `ci` | CI/CD pipeline changes |
| `revert` | Reverting a previous commit |

### Signing
- All commits and tags must be SSH-signed.
- The "Verified" badge must appear on GitHub for every commit.
- Never use `--no-gpg-sign` or skip signing.

---

## Repository Conventions

### Naming
- Repository names use snake_case with a type prefix that describes the primary
  artifact (e.g., `lib_`, `tool_`, `fw_`, `script_`, `config_`, `docs_`).
- Example: `fw_quadcopter_controller`, `lib_pid_tuner`, `tool_log_parser`

### Visibility
- Repositories are private by default.
- Making a repository public is a deliberate decision, not a default.

### Licensing
- Every repository must have an explicit license file.
- No silent defaults — the license must be a conscious choice.

---

## Code Review Format

Reviews use a three-tier severity system. Every comment explains WHY, not just WHAT.

### Critical
- Must be fixed before the PR can be merged.
- Represents correctness bugs, security issues, or violations of core conventions.
- Example: "Critical: This hardcodes the API key in the source file. Secrets must
  never be committed — move this to `.env` and add `.env` to `.gitignore`."

### Warning
- Should be fixed. If intentionally skipped, the author must explain why in the PR.
- Represents suboptimal patterns, missing error handling, or style drift.
- Example: "Warning: This function has no error handling for the case where the file
  doesn't exist. Silent failure here will be very hard to debug."

### Suggestion
- Optional improvement with a clear rationale. Author decides whether to act.
- Example: "Suggestion: Extracting this block into a helper function would make it
  easier to test in isolation, but it works fine as-is for now."

---

## Comment Style

Comments are written in a teaching style: they explain the reasoning and context,
not just what the code does.

- Bad: `# increment i`
- Good: `# i must start at 1, not 0 — the protocol uses 1-based indexing`

Comments answer the question "why was this done this way?" not "what does this do?"
(the code itself answers what; the comment answers why).

---

## Uncertainty Handling

### High-Impact Decisions — Ask Explicitly
Before proceeding with any of the following, stop and ask the user for confirmation:
- Architecture decisions (choosing a library, restructuring modules)
- Destructive operations (deleting files, dropping tables, force-pushing)
- Security-relevant choices (authentication method, crypto algorithm, secret storage)
- Anything that would be difficult or impossible to reverse

### Low-Impact Decisions — State and Proceed
For minor choices, state the assumption made and continue:
- Variable and function names
- Minor structural choices (where to put a helper function)
- Formatting decisions within the established style

Example: "Naming this helper `_parse_packet` to match the existing `_parse_header`
convention — proceeding."

---

## Platform-Specific Rules

> Note: This section is extended by the `CLAUDE.md` import system.
> Uncomment the relevant platform import in `CLAUDE.md` to load additional
> language- and platform-specific rules that supplement the universal rules above.

Platform imports live in `~/.claude/rules/` and cover:
- `arduino.md` — ArduPilot/Arduino firmware conventions
- `python.md` — Python (uv, ruff, pytest) conventions
- `shell.md` — bash/zsh and PowerShell conventions
- `assembly.md` — NASM x86-64 assembly conventions
- `vbscript.md` — VBScript/WSH conventions
