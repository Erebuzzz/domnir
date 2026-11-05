"""Bounded Microsandbox lifecycle for feasibility work on a trusted host."""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Self

IMAGE = "python:3.12-slim@sha256:1148dbb014615300fa7e713b2f94f550c0d1c69780c0805f84f093ceee34dd0b"
RUNTIME_VERSION = "msb 0.7.13"


class SandboxError(RuntimeError):
    """The runtime did not establish or clean up the required sandbox."""


def validate_controller_source(source: bytes) -> str:
    if (
        not isinstance(source, bytes)
        or not 1 <= len(source) <= 32768
        or b"\x00" in source
    ):
        raise ValueError("Controller must be 1 to 32768 bytes of UTF-8 Python source")
    try:
        text = source.decode("utf-8")
        tree = ast.parse(text, filename="controller.py")
    except (
        UnicodeDecodeError,
        SyntaxError,
        ValueError,
        RecursionError,
        MemoryError,
    ) as error:
        raise ValueError("Controller source must be valid UTF-8 Python") from error
    if not any(
        isinstance(node, ast.FunctionDef) and node.name == "observe"
        for node in tree.body
    ):
        raise ValueError(
            "Controller must define a synchronous top-level observe function"
        )
    return hashlib.sha256(source).hexdigest()


class SandboxLease:
    def __init__(self, executable: Path, *, duration_seconds: int = 120) -> None:
        if not 1 <= duration_seconds <= 300:
            raise ValueError("Sandbox duration must be between 1 and 300 seconds")
        self.executable = str(executable)
        self.name = f"domnir-{uuid.uuid4().hex}"
        self.duration_seconds = duration_seconds
        self.cleanup_succeeded: bool | None = None
        self.active = False

    def _run(
        self, *arguments: str, timeout: int = 30
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [self.executable, *arguments],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )

    def __enter__(self) -> Self:
        version = self._run("--version").stdout.strip()
        if version != RUNTIME_VERSION:
            raise SandboxError(f"Unsupported Microsandbox version: {version}")
        try:
            self._run(
                "create",
                "--name",
                self.name,
                "--cpus",
                "1",
                "--memory",
                "512M",
                "--no-net",
                "--max-duration",
                f"{self.duration_seconds}s",
                IMAGE,
                timeout=120,
            )
            result = self._run("inspect", "--format", "json", self.name)
            config = json.loads(result.stdout)["active_config"]
            policy = config["network"]["policy"]
            resources = config["resources"]
            lifecycle = config["lifecycle"]
            if (
                policy["default_egress"] != "deny"
                or policy["default_ingress"] != "deny"
                or policy["rules"]
                or config["network"]["ports"]
                or config["mounts"]
                or resources["cpus"] != 1
                or resources["max_cpus"] != 1
                or resources["memory_mib"] != 512
                or resources["max_memory_mib"] != 512
                or lifecycle["max_duration_secs"] != self.duration_seconds
                or config["manifest_digest"] != IMAGE.rsplit("@", 1)[1]
            ):
                raise SandboxError(
                    "Runtime configuration does not match the isolation policy"
                )
            self.active = True
            return self
        except Exception as error:
            try:
                self.remove()
            except Exception as cleanup_error:
                raise SandboxError(
                    f"Sandbox setup and cleanup failed for {self.name}"
                ) from cleanup_error
            raise SandboxError("Sandbox setup failed") from error

    def remove(self) -> None:
        self.active = False
        try:
            self._run("rm", "--force", self.name)
        except (subprocess.SubprocessError, OSError) as error:
            self.cleanup_succeeded = False
            raise SandboxError(f"Sandbox cleanup failed for {self.name}") from error
        self.cleanup_succeeded = True

    def install_controller(self, source: bytes) -> str:
        if not self.active:
            raise SandboxError("A verified active sandbox is required")
        digest = validate_controller_source(source)
        with tempfile.TemporaryDirectory(prefix="domnir-controller-") as directory:
            path = Path(directory) / "controller.py"
            path.write_bytes(source)
            self._run(
                "copy", str(path), f"{self.name}:/tmp/domnir-controller.py", timeout=30
            )
        return digest

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.remove()
