# Releasing

Releases are intentionally manual while hosted CI is disabled. Do not enable GitHub Actions solely for a release unless repository credits/policy allow it.

## 1. Start from a clean checkout

```bash
git switch main
git pull --ff-only
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip build
pip install -e '.[dev,x]'
```

## 2. Run local verification

```bash
python -m compileall -q src tests scripts
python -m ruff check .
python -m pytest -q
python scripts/local_verify.py
```

Run the Streamable HTTP and backend smoke tests described in `CODEX_VERIFY.md` and `docs/oss-release.md` as appropriate for the release.

## 3. Verify the container

```bash
docker build -t agent-reach-mcp:release-test .
```

The bare image should fail closed when started with its default unauthenticated `0.0.0.0` configuration.

Then verify the private Compose path:

```bash
docker compose -f compose.private.yml up -d --build
python scripts/http_verify.py
docker compose -f compose.private.yml down
```

Confirm the published port is host-loopback only.

## 4. Build package artifacts

```bash
rm -rf dist build
python -m build
```

Inspect the wheel/sdist metadata and test-install them in a fresh virtual environment.

Do **not** publish to PyPI while the package metadata contains the pinned direct GitHub reference to Agent Reach. Source/GitHub releases are allowed before that packaging issue is resolved.

## 5. Update version and changelog

- Update the project version in `pyproject.toml`.
- Move relevant `CHANGELOG.md` entries from `Unreleased` to `## X.Y.Z - YYYY-MM-DD`.
- Commit those release metadata changes.

## 6. Tag and publish GitHub release

After the release commit has been reviewed:

```bash
git tag -s vX.Y.Z -m "agent-reach-mcp vX.Y.Z"
git push origin vX.Y.Z
```

An unsigned annotated tag may be used if signing is not configured, but signed tags are preferred.

Create the GitHub release from the exact tag and use the corresponding changelog section as the release notes. Attach locally built artifacts only after verifying they were built from that tagged commit.

## 7. Post-release

- Restore an empty `Unreleased` section if needed.
- Verify the README's installation and deployment instructions still match the released version.
- Recheck ChatGPT-specific documentation against current OpenAI product behavior before announcing ChatGPT compatibility.
