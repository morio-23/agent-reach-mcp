# Changelog

All notable changes to this project are documented here.

The project follows semantic versioning after the first public release. Until then, `Unreleased` describes the current pre-release state.

## Unreleased

### Added

- Read-only MCP gateway for Agent Reach.
- stdio and Streamable HTTP transports.
- `get_capabilities`, `read_url`, X read/search tools, and YouTube transcript tool.
- Optional static bearer-token and OAuth/OIDC resource-server authentication.
- Local verification scripts and tests.
- ChatGPT remote-connection and Linux/WSL2 self-hosting documentation.
- Docker/Compose private deployment baseline.
- Security, contribution, and OSS release guidance.
- Optional X image posting through Twifork with up to four PNG/JPEG/WebP images and alt text.

### Security

- Unauthenticated non-loopback HTTP is denied by default.
- Arbitrary shell/CLI execution and unrestricted local-file access are not exposed through MCP.
- Backend credentials remain server-side.
- X media URLs must use public HTTPS targets; private/loopback DNS resolutions, oversized images, unsupported image formats, and excessive redirects are rejected before upload.

## Release policy

For each release:

1. Move user-visible entries from `Unreleased` into a versioned section with the release date.
2. Keep changes grouped under headings such as `Added`, `Changed`, `Fixed`, `Removed`, and `Security`.
3. Tag the exact reviewed commit as `vX.Y.Z`.
4. Do not include credentials, private URLs, captured cookies, or machine-specific information in release notes.
