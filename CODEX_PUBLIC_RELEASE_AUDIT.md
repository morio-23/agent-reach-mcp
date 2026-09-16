# Codex public release audit

This checklist is intentionally mechanical. Do not redesign or refactor the project.

## Goal

Run the final local checks needed before changing the GitHub repository visibility from private to public.

## Rules

- Do not run GitHub Actions.
- Do not add new product features.
- Do not configure real X cookies or OAuth credentials.
- Do not publish to PyPI.
- If a command fails, identify the concrete cause and make only the smallest required fix.
- Commit/push only when a code/documentation fix is actually required.

## Commands

From `feature/public-release-audit` in a clean worktree and the existing project virtual environment:

```bash
python -m compileall -q src tests scripts
python -m ruff check .
python -m pytest -q
python scripts/public_release_audit.py
```

The audit script performs:

- clean-worktree validation;
- suspicious secret-bearing filename scan across all local git refs/history;
- high-confidence credential-pattern scan across all local git refs/history;
- installed direct/transitive dependency license inventory generation;
- wheel build;
- wheel metadata validation;
- explicit detection of the known Agent Reach direct-URL dependency / PyPI blocker (#7).

Generated files are written under `.release-audit/` and are git-ignored.

## Report only

1. compileall result
2. ruff result
3. pytest result
4. history secret scan result and number of commits scanned
5. `.release-audit/licenses.csv` package count
6. all packages whose license metadata is `UNKNOWN`
7. any dependency license that looks restrictive, copyleft, source-available, proprietary, or otherwise unsuitable for this MIT project
8. wheel filename and metadata validation result
9. whether the expected PyPI direct-URL blocker was detected
10. any code fix made and commit SHA
11. whether there is any remaining blocker to making the GitHub repository public (separate this from PyPI publication blockers)
