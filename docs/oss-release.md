# OSS release checklist

Use this checklist before changing the repository visibility to public or publishing a release.

## Repository hygiene

- [ ] No secrets, cookies, OAuth tokens, API keys, private URLs, or machine-specific paths are present in tracked files or git history.
- [ ] `.env` remains ignored.
- [ ] Example credentials are placeholders only.
- [ ] README clearly states that this project is independently maintained and not affiliated with Agent Reach maintainers.
- [ ] LICENSE, SECURITY.md, and CONTRIBUTING.md are present.

## Dependency / packaging review

- [ ] Review all direct and transitive dependency licenses.
- [ ] Confirm the pinned upstream Agent Reach commit remains compatible with the implemented adapter API.
- [ ] Resolve the current direct GitHub dependency before any PyPI publication. Public package indexes generally do not accept distributions whose metadata requires an arbitrary direct URL dependency.
- [ ] Until that is resolved, document installation from the GitHub repository/source checkout rather than claiming PyPI support.
- [ ] Build the package locally and inspect wheel metadata.

Suggested checks:

```bash
python -m build
python -m pip install dist/*.whl
```

## Quality checks

- [ ] `python -m compileall -q src tests scripts`
- [ ] `python -m ruff check .`
- [ ] `python -m pytest -q`
- [ ] `python scripts/local_verify.py`
- [ ] Streamable HTTP verification succeeds.
- [ ] Static-token rejection/success behavior is rechecked.
- [ ] `read_url` live smoke test succeeds.
- [ ] YouTube transcript live smoke test succeeds on a known-captioned video.
- [ ] X live tests are performed when `twitter-cli` credentials are intentionally configured.

GitHub Actions are optional; local verification is sufficient when hosted CI is intentionally disabled.

## Container checks

- [ ] `docker build` succeeds.
- [ ] Default container fails closed if started with unauthenticated `0.0.0.0` listening and no explicit override/auth configuration.
- [ ] `compose.private.yml` publishes only to host loopback.
- [ ] Public container deployment examples use OAuth and HTTPS at the ingress/reverse proxy.
- [ ] No credential file is baked into the image.

## Security review

- [ ] No tool exposes arbitrary shell/CLI execution.
- [ ] No tool exposes unrestricted local-file access.
- [ ] No tool returns cookies, tokens, or server-side credentials.
- [ ] Subprocess calls use argument arrays and `shell=False`.
- [ ] URL/identifier validation is active.
- [ ] Timeouts and output-size limits are active.
- [ ] Fetched content is treated as untrusted data.
- [ ] Unauthenticated non-loopback HTTP remains blocked by default.
- [ ] OAuth issuer/audience/JWKS validation is documented and tested against a real IdP before recommending public deployment.

## Documentation review

- [ ] README install steps work from a fresh checkout.
- [ ] `docs/chatgpt.md` matches current ChatGPT custom-MCP behavior.
- [ ] `docs/self-hosting.md` works on a clean Linux/WSL2 host.
- [ ] ChatGPT plan/workspace availability language is current at release time.
- [ ] Static-token auth is described as a generic/private MCP-client option, not assumed to be a ChatGPT UI authentication method.

## Release decision

The repository can become public before PyPI packaging is solved, as long as installation is documented from source and the direct Agent Reach dependency is clearly explained. PyPI publication should remain blocked until the upstream dependency strategy is compatible with package-index metadata rules.
