## Summary
<!-- What does this PR do? 1-3 bullet points -->
-

## Related Issue
Closes #

## Type of Change
- [ ] feat: New feature
- [ ] fix: Bug fix
- [ ] docs: Documentation only
- [ ] chore: Maintenance/dependencies
- [ ] refactor: Code restructuring
- [ ] test: Tests only
- [ ] ci: CI/CD changes

## Testing Performed
<!-- Describe what you tested and how -->

## Checklist
- [ ] Commit message follows Conventional Commits format
- [ ] Commit is SSH-signed (Verified badge will appear on GitHub)
- [ ] No secrets or credentials included
- [ ] CHANGELOG.md updated (for feat/fix)
- [ ] Documentation updated (if applicable)
- [ ] Branch is up to date with main

## Platform-Specific Checks

### Python
- [ ] `ruff check .` passes with no errors
- [ ] `ruff format .` applied
- [ ] Tests pass: `uv run pytest`
- [ ] `.env.example` updated if new env vars added

### PowerShell
- [ ] `Invoke-ScriptAnalyzer -Path . -Recurse` passes
- [ ] Tests pass: `Invoke-Pester`
- [ ] Tested on PowerShell 7+

### bash/zsh
- [ ] `shellcheck bin/*.sh lib/*.sh` passes
- [ ] Tests pass: `bats tests/`

### NASM Assembly
- [ ] Assembles without errors: `make`
- [ ] Tested in x64dbg debugger

### ArduPilot
- [ ] Firmware compiles without errors
- [ ] Parameters validated
- [ ] Mission scripts tested in SITL (if applicable)
