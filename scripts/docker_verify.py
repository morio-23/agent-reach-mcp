from __future__ import annotations

import os
import shlex
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "agent-reach-mcp-verify"
COMPOSE_FILE = ROOT / "compose.private.yml"


class VerificationError(RuntimeError):
    pass


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _format_command(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def _run(
    command: list[str],
    *,
    env: dict[str, str],
    check: bool = True,
    timeout: float = 120,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise VerificationError(f"command not found: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise VerificationError(
            f"command timed out after {timeout:g}s: {_format_command(command)}"
        ) from exc

    if check and result.returncode != 0:
        output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
        raise VerificationError(
            f"command failed ({result.returncode}): {_format_command(command)}\n"
            + output[-5000:]
        )
    return result


def _compose(*args: str) -> list[str]:
    return [
        "docker",
        "compose",
        "-p",
        PROJECT,
        "-f",
        str(COMPOSE_FILE),
        *args,
    ]


def main() -> None:
    port = _free_loopback_port()
    env = os.environ.copy()
    env["AGENT_REACH_MCP_HOST_PORT"] = str(port)

    print(f"Docker verification project: {PROJECT}")
    print(f"Temporary host port: 127.0.0.1:{port}")

    try:
        _run(["docker", "--version"], env=env, timeout=15)
        _run(["docker", "compose", "version"], env=env, timeout=15)
        print("OK: Docker and Compose are available")

        _run(_compose("config"), env=env, timeout=30)
        print("OK: compose.private.yml parses")

        _run(_compose("build"), env=env, timeout=900)
        print("OK: Docker image builds")

        image_result = _run(
            _compose("images", "-q", "agent-reach-mcp"), env=env, timeout=30
        )
        image_ids = [line.strip() for line in image_result.stdout.splitlines() if line.strip()]
        if not image_ids:
            raise VerificationError("could not resolve the Compose image ID")
        image_id = image_ids[0]

        try:
            default_run = subprocess.run(
                ["docker", "run", "--rm", image_id],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                timeout=15,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise VerificationError(
                "default container stayed running; unauthenticated 0.0.0.0 must fail closed"
            ) from exc

        fail_closed_output = (
            (default_run.stdout or "") + "\n" + (default_run.stderr or "")
        ).lower()
        expected_error = "unauthenticated remote listening is disabled"
        if default_run.returncode == 0 or expected_error not in fail_closed_output:
            raise VerificationError(
                "default image did not fail closed for the expected security reason\n"
                + fail_closed_output[-3000:]
            )
        print("OK: default container fails closed")

        _run(_compose("up", "-d"), env=env, timeout=120)
        print("OK: private Compose service starts")

        port_result = _run(
            _compose("port", "agent-reach-mcp", "8080"), env=env, timeout=30
        )
        binding = port_result.stdout.strip()
        expected_binding = f"127.0.0.1:{port}"
        if expected_binding not in binding:
            raise VerificationError(
                f"expected loopback-only publish {expected_binding}, got: {binding!r}"
            )
        print(f"OK: host publish is loopback-only ({binding})")

        _run(
            _compose(
                "exec",
                "-T",
                "agent-reach-mcp",
                "sh",
                "-lc",
                "command -v twitter >/dev/null && python -c 'import yt_dlp'",
            ),
            env=env,
            timeout=30,
        )
        print("OK: twitter-cli and yt-dlp are installed")

        _run(
            _compose(
                "exec",
                "-T",
                "agent-reach-mcp",
                "sh",
                "-lc",
                "test \"$(id -u)\" != 0 && test -w /home/appuser/.agent-reach && "
                "touch /home/appuser/.agent-reach/.verify-write && "
                "rm /home/appuser/.agent-reach/.verify-write",
            ),
            env=env,
            timeout=30,
        )
        print("OK: service is non-root and Agent Reach volume is writable")

        verify_command = [
            sys.executable,
            str(ROOT / "scripts" / "http_verify.py"),
            "--url",
            f"http://127.0.0.1:{port}/mcp",
        ]
        last_result: subprocess.CompletedProcess[str] | None = None
        for _ in range(8):
            last_result = _run(
                verify_command,
                env=env,
                check=False,
                timeout=45,
            )
            if last_result.returncode == 0:
                break
            time.sleep(1)
        else:
            assert last_result is not None
            output = ((last_result.stdout or "") + "\n" + (last_result.stderr or "")).strip()
            raise VerificationError("MCP HTTP verification failed\n" + output[-5000:])

        print("OK: Streamable HTTP MCP handshake and get_capabilities succeed")
        print("Docker verification passed")
    finally:
        try:
            cleanup = _run(
                _compose("down", "-v", "--remove-orphans"),
                env=env,
                check=False,
                timeout=120,
            )
        except VerificationError as exc:
            print(f"WARNING: Docker verification cleanup could not run: {exc}", file=sys.stderr)
        else:
            if cleanup.returncode != 0:
                print("WARNING: Docker verification cleanup failed", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except VerificationError as exc:
        print(f"Docker verification failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
