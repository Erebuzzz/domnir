import hashlib
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from domnir.sandbox import IMAGE, RUNTIME_VERSION, SandboxError, SandboxLease


class SandboxLifecycleTests(unittest.TestCase):
    def config(self):
        return {
            "active_config": {
                "manifest_digest": IMAGE.rsplit("@", 1)[1],
                "network": {
                    "policy": {
                        "default_egress": "deny",
                        "default_ingress": "deny",
                        "rules": [],
                    },
                    "ports": [],
                },
                "mounts": [],
                "resources": {
                    "cpus": 1,
                    "max_cpus": 1,
                    "memory_mib": 512,
                    "max_memory_mib": 512,
                },
                "lifecycle": {"max_duration_secs": 120},
            }
        }

    def test_policy_mismatch_removes_sandbox_and_fails_closed(self):
        config = self.config()
        config["active_config"]["network"]["policy"]["default_egress"] = "allow"
        calls = []

        def run(arguments, **kwargs):
            calls.append(arguments)
            stdout = RUNTIME_VERSION if "--version" in arguments else json.dumps(config)
            return subprocess.CompletedProcess(arguments, 0, stdout, "")

        lease = SandboxLease(Path("msb"))
        with (
            patch("domnir.sandbox.subprocess.run", side_effect=run),
            self.assertRaises(SandboxError),
            lease,
        ):
            self.fail("Policy mismatch must not yield a sandbox")
        self.assertTrue(lease.cleanup_succeeded)
        self.assertEqual(calls[-1][1:3], ["rm", "--force"])

    def test_cleanup_failure_is_reported(self):
        lease = SandboxLease(Path("msb"))
        failure = subprocess.CalledProcessError(1, "msb")
        with (
            patch("domnir.sandbox.subprocess.run", side_effect=failure),
            self.assertRaises(SandboxError),
        ):
            lease.remove()
        self.assertFalse(lease.cleanup_succeeded)

    def test_controller_bytes_are_copied_without_host_execution(self):
        lease = SandboxLease(Path("msb"))
        lease.active = True
        source = b"raise RuntimeError('must never run on the host')\ndef observe(obs): pass\n"
        seen = []

        def run(arguments, **kwargs):
            path = Path(arguments[2])
            self.assertEqual(path.read_bytes(), source)
            seen.append(path)
            return subprocess.CompletedProcess(arguments, 0, "", "")

        with patch("domnir.sandbox.subprocess.run", side_effect=run):
            self.assertEqual(
                lease.install_controller(source), hashlib.sha256(source).hexdigest()
            )
        self.assertFalse(seen[0].exists())

    def test_rejects_controller_without_active_lease_and_bad_source(self):
        lease = SandboxLease(Path("msb"))
        with self.assertRaises(SandboxError):
            lease.install_controller(b"pass")
        lease.active = True
        for source in (
            b"",
            b"x" * 32769,
            b"\x00",
            b"\xff",
            b"def (",
            b"pass",
            b"async def observe(x): pass",
        ):
            with self.subTest(source=source[:5]), self.assertRaises(ValueError):
                lease.install_controller(source)


if __name__ == "__main__":
    unittest.main()
