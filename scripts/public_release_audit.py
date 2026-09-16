from __future__ import annotations

import csv
import importlib.metadata as metadata
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT_DIR = ROOT / ".release-audit"
SELF_PATH = "scripts/public_release_audit.py"


class AuditError(RuntimeError):
    pass


def _run(command: list[str], *, check: bool = True, timeout: float = 300) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise AuditError(f"command not found: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise AuditError(f"command timed out: {' '.join(command)}") from exc

    if check and result.returncode != 0:
        output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
        raise AuditError(f"command failed ({result.returncode}): {' '.join(command)}\n{output[-6000:]}")
    return result


def _assert_clean_worktree() -> None:
    status = _run(["git", "status", "--porcelain"]).stdout.strip()
    if status:
        raise AuditError("worktree must be clean before a public-release audit")
    print("OK: worktree is clean")


def _audit_history_filenames() -> None:
    result = _run(["git", "log", "--all", "--pretty=format:", "--name-only"])
    paths = {line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()}

    suspicious: list[str] = []
    for path in sorted(paths):
        lower = path.lower()
        name = Path(lower).name
        if name == ".env" or lower.startswith(".agent-reach/"):
            suspicious.append(path)
        elif name in {"id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "cookies.json"}:
            suspicious.append(path)
        elif Path(lower).suffix in {".pem", ".key", ".p12", ".pfx"}:
            suspicious.append(path)

    if suspicious:
        raise AuditError("suspicious secret-bearing filenames exist in git history:\n" + "\n".join(suspicious))
    print("OK: git history contains no suspicious secret-bearing filenames")


def _secret_pattern() -> str:
    # Keep the audit source itself out of the search so pattern literals cannot
    # self-match. These are intentionally high-confidence token/key signatures.
    patterns = [
        r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
        r"AKIA[0-9A-Z]{16}",
        r"github_pat_[A-Za-z0-9_]{20,}",
        r"gh[pousr]_[A-Za-z0-9]{20,}",
        r"sk-[A-Za-z0-9_-]{24,}",
        r"xox[baprs]-[A-Za-z0-9-]{20,}",
        r"AIza[0-9A-Za-z_-]{35}",
    ]
    return "(?:" + ")|(?:".join(patterns) + ")"


def _audit_history_content() -> None:
    commits = [x.strip() for x in _run(["git", "rev-list", "--all"]).stdout.splitlines() if x.strip()]
    if not commits:
        raise AuditError("git history is empty")

    regex = _secret_pattern()
    hits: set[str] = set()
    for commit in commits:
        result = _run(
            [
                "git",
                "grep",
                "-I",
                "-n",
                "-E",
                regex,
                commit,
                "--",
                ".",
                f":(exclude){SELF_PATH}",
            ],
            check=False,
            timeout=60,
        )
        if result.returncode not in {0, 1}:
            raise AuditError(f"git grep failed while scanning {commit}: {(result.stderr or '').strip()}")
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if line.strip():
                    hits.add(line.strip())

    if hits:
        raise AuditError(
            "possible credentials found in git history; inspect before making the repository public:\n"
            + "\n".join(sorted(hits)[:100])
        )
    print(f"OK: scanned {len(commits)} commits for high-confidence credential patterns")


def _normalize_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _requirement_name(requirement: str) -> str | None:
    match = re.match(r"\s*([A-Za-z0-9_.-]+)", requirement)
    return _normalize_name(match.group(1)) if match else None


def _license_text(dist: metadata.Distribution) -> str:
    values: list[str] = []
    for key in ("License-Expression", "License"):
        value = dist.metadata.get(key)
        if value and value.strip() and value.strip().upper() != "UNKNOWN":
            values.append(value.strip())
    for classifier in dist.metadata.get_all("Classifier") or []:
        if classifier.startswith("License ::"):
            values.append(classifier)
    return " | ".join(dict.fromkeys(values)) or "UNKNOWN"


def _write_license_inventory() -> tuple[int, int]:
    distributions = {}
    for dist in metadata.distributions():
        name = dist.metadata.get("Name")
        if name:
            distributions[_normalize_name(name)] = dist

    roots = {
        "agent-reach-mcp",
        "agent-reach",
        "mcp",
        "pydantic",
        "pydantic-settings",
        "pyjwt",
        "twitter-cli",
    }
    pending = list(roots)
    reachable: set[str] = set()

    while pending:
        name = pending.pop()
        if name in reachable:
            continue
        dist = distributions.get(name)
        if dist is None:
            continue
        reachable.add(name)
        for requirement in dist.requires or []:
            dependency = _requirement_name(requirement)
            if dependency and dependency in distributions and dependency not in reachable:
                pending.append(dependency)

    rows = []
    unknown = 0
    for name in sorted(reachable):
        dist = distributions[name]
        license_text = _license_text(dist)
        if license_text == "UNKNOWN":
            unknown += 1
        rows.append(
            {
                "name": dist.metadata.get("Name") or name,
                "version": dist.version,
                "license": license_text,
                "homepage": dist.metadata.get("Home-page") or dist.metadata.get("Project-URL") or "",
            }
        )

    AUDIT_DIR.mkdir(exist_ok=True)
    csv_path = AUDIT_DIR / "licenses.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["name", "version", "license", "homepage"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"OK: wrote transitive installed-dependency license inventory: {csv_path.relative_to(ROOT)} ({len(rows)} packages)")
    if unknown:
        print(f"NOTE: {unknown} installed packages have UNKNOWN license metadata and require manual review")
    return len(rows), unknown


def _build_and_inspect_wheel() -> dict[str, object]:
    AUDIT_DIR.mkdir(exist_ok=True)
    wheel_dir = AUDIT_DIR / "wheel"
    if wheel_dir.exists():
        shutil.rmtree(wheel_dir)
    wheel_dir.mkdir(parents=True)

    _run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--wheel-dir",
            str(wheel_dir),
            ".",
        ],
        timeout=900,
    )
    wheels = list(wheel_dir.glob("agent_reach_mcp-*.whl"))
    if len(wheels) != 1:
        raise AuditError(f"expected exactly one project wheel, found {len(wheels)}")

    wheel = wheels[0]
    with zipfile.ZipFile(wheel) as archive:
        metadata_names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(metadata_names) != 1:
            raise AuditError("wheel does not contain exactly one METADATA file")
        metadata_text = archive.read(metadata_names[0]).decode("utf-8", errors="strict")

    if "Name: agent-reach-mcp" not in metadata_text or "Version: 0.1.0" not in metadata_text:
        raise AuditError("wheel metadata has an unexpected project name/version")

    direct_agent_reach = [
        line for line in metadata_text.splitlines() if line.startswith("Requires-Dist: agent-reach")
    ]
    if not direct_agent_reach:
        raise AuditError("wheel metadata is missing the Agent Reach dependency")

    direct_url = any("http" in line for line in direct_agent_reach)
    report = {
        "wheel": wheel.name,
        "agent_reach_requires_dist": direct_agent_reach,
        "pypi_direct_url_blocker": direct_url,
    }
    (AUDIT_DIR / "wheel-metadata.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"OK: built and inspected wheel: {wheel.name}")
    if direct_url:
        print("EXPECTED BLOCKER: wheel metadata contains the tracked direct Agent Reach URL dependency (#7); do not publish this artifact to PyPI")
    return report


def main() -> None:
    os.chdir(ROOT)
    _assert_clean_worktree()
    _audit_history_filenames()
    _audit_history_content()
    package_count, unknown_licenses = _write_license_inventory()
    wheel_report = _build_and_inspect_wheel()

    summary = {
        "history_secret_scan": "passed",
        "license_inventory_packages": package_count,
        "unknown_license_metadata": unknown_licenses,
        "wheel": wheel_report,
        "github_public_release_blocked": False,
        "pypi_release_blocked": bool(wheel_report["pypi_direct_url_blocker"]),
    }
    AUDIT_DIR.mkdir(exist_ok=True)
    (AUDIT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("Public release audit completed. Review UNKNOWN license rows manually before changing repository visibility.")


if __name__ == "__main__":
    try:
        main()
    except AuditError as exc:
        print(f"Public release audit failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
