"""Tests for security middleware, limits, and defensive boundaries."""

from __future__ import annotations

import unittest
from fastapi.testclient import TestClient

from domnir.api.app import app
from domnir.api.security import RateLimiter, validate_id_param


class SecurityDefensesTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_security_headers_present_on_responses(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(resp.headers.get("X-Frame-Options"), "DENY")
        self.assertIn("default-src 'self'", resp.headers.get("Content-Security-Policy", ""))
        self.assertEqual(resp.headers.get("Referrer-Policy"), "strict-origin-when-cross-origin")
        self.assertIn("camera=()", resp.headers.get("Permissions-Policy", ""))

    def test_request_size_limit_rejection(self):
        huge_headers = {"content-length": "70000"}
        resp = self.client.post("/specs/validate", json={"spec": {}}, headers=huge_headers)
        self.assertEqual(resp.status_code, 413)
        self.assertIn("exceeds limit", resp.json()["detail"])

    def test_court_record_size_limit_allows_large_payload_up_to_2mib(self):
        # 100 KiB should be rejected on /specs/validate but allowed through middleware on /court-records/verify
        huge_headers = {"content-length": "100000"}
        resp_specs = self.client.post("/specs/validate", json={"spec": {}}, headers=huge_headers)
        self.assertEqual(resp_specs.status_code, 413)

        # > 2 MiB should be rejected even on /court-records/verify
        excessive_headers = {"content-length": "2500000"}
        resp_court = self.client.post("/court-records/verify", json={}, headers=excessive_headers)
        self.assertEqual(resp_court.status_code, 413)

    def test_controller_code_size_boundary_enforced(self):
        oversized_code = "def observe(obs):\n" + "    x = 1\n" * 3500  # > 32 KiB
        self.assertGreater(len(oversized_code.encode("utf-8")), 32768)

        payload = {
            "spec": {
                "target_altitude_m": 0.10,
                "altitude_tolerance_m": 0.05,
                "min_allowed_altitude_m": 0.05,
                "max_allowed_altitude_m": 1.00,
                "mission_duration_s": 0.04,
                "dt_s": 0.002,
                "disturbance_force_z_min": -0.05,
                "disturbance_force_z_max": 0.05,
            },
            "controller_source": oversized_code,
        }
        resp = self.client.post("/experiments/run", json=payload)
        self.assertEqual(resp.status_code, 422)
        self.assertIn("32 KiB", str(resp.json()))

    def test_path_traversal_identifier_rejected(self):
        for bad_id in [
            "../../etc/passwd",
            "..\\..\\windows\\system32",
            "../../../secret",
            "id-with-slashes/evil",
            "id-with;semicolon",
            "a" * 65,  # Exceeds max length 64
        ]:
            with self.subTest(bad_id=bad_id):
                with self.assertRaises(ValueError):
                    validate_id_param(bad_id, "test_id")

                resp = self.client.get(f"/experiments/{bad_id}")
                self.assertIn(resp.status_code, (400, 404))

    def test_rate_limiter_unit_logic(self):
        limiter = RateLimiter(default_limit=5, heavy_limit=2, window_seconds=60.0)
        client_ip = "198.51.100.1"

        # Read endpoint allowance
        for _ in range(5):
            allowed, _, _ = limiter.is_allowed(client_ip, "/health")
            self.assertTrue(allowed)
        allowed, limit, retry_after = limiter.is_allowed(client_ip, "/health")
        self.assertFalse(allowed)
        self.assertEqual(limit, 5)
        self.assertGreater(retry_after, 0.0)

        # Heavy endpoint allowance on separate IP
        heavy_ip = "198.51.100.2"
        for _ in range(2):
            allowed, _, _ = limiter.is_allowed(heavy_ip, "/experiments/run")
            self.assertTrue(allowed)
        allowed, limit, _ = limiter.is_allowed(heavy_ip, "/experiments/run")
        self.assertFalse(allowed)
        self.assertEqual(limit, 2)

    def test_light_requests_do_not_exhaust_heavy_quota_on_same_ip(self):
        limiter = RateLimiter(default_limit=10, heavy_limit=3, window_seconds=60.0)
        same_ip = "198.51.100.3"

        # Make 4 lightweight requests
        for _ in range(4):
            allowed, _, _ = limiter.is_allowed(same_ip, "/health")
            self.assertTrue(allowed)

        # Client must still be allowed all 3 heavy requests
        for _ in range(3):
            allowed, limit, _ = limiter.is_allowed(same_ip, "/containment/run")
            self.assertTrue(allowed)
            self.assertEqual(limit, 3)

        # 4th heavy request must be rejected under heavy limit
        allowed, limit, retry_after = limiter.is_allowed(same_ip, "/containment/run")
        self.assertFalse(allowed)
        self.assertEqual(limit, 3)
        self.assertGreater(retry_after, 0.0)

    def test_chunked_streaming_request_size_limit_rejection(self):
        def streaming_body():
            for _ in range(70):
                yield b"X" * 1024  # 70 KiB total > 64 KiB limit

        resp = self.client.post("/specs/validate", content=streaming_body())
        self.assertEqual(resp.status_code, 413)
        self.assertIn("exceeds limit", resp.json()["detail"])

    def test_invalid_content_length_rejected(self):
        # Negative content length
        resp = self.client.post("/specs/validate", content=b"foo", headers={"content-length": "-1"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Invalid Content-Length", resp.json()["detail"])

        # Non-integer content length
        resp = self.client.post("/specs/validate", content=b"foo", headers={"content-length": "invalid"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Invalid Content-Length", resp.json()["detail"])

    def test_rate_limiter_http_middleware_integration(self):
        from fastapi import FastAPI
        from domnir.api.security import RateLimitMiddleware

        test_app = FastAPI()
        test_limiter = RateLimiter(default_limit=2, heavy_limit=1, window_seconds=60.0)
        test_app.add_middleware(RateLimitMiddleware, limiter=test_limiter, enforce_testclient=True)

        @test_app.get("/ping")
        def ping():
            return {"ping": "pong"}

        c = TestClient(test_app)
        # Request 1: allowed
        r1 = c.get("/ping")
        self.assertEqual(r1.status_code, 200)

        # Request 2: allowed
        r2 = c.get("/ping")
        self.assertEqual(r2.status_code, 200)

        # Request 3: throttled
        r3 = c.get("/ping")
        self.assertEqual(r3.status_code, 429)
        self.assertIn("Retry-After", r3.headers)
        self.assertIn("Too many requests", r3.json()["detail"])

    def test_forwarded_for_spoofing_rejected_for_untrusted_peer(self):
        import asyncio
        from domnir.api.security import RateLimitMiddleware, RateLimiter
        from starlette.responses import JSONResponse

        async def dummy_app(scope, receive, send):
            res = JSONResponse({"ok": True})
            await res(scope, receive, send)

        limiter = RateLimiter(default_limit=1, heavy_limit=1, window_seconds=60.0)
        mw = RateLimitMiddleware(dummy_app, limiter=limiter, enforce_testclient=True)

        # Peer is an untrusted external IP trying to spoof X-Forwarded-For to bypass limits
        sent_messages = []
        async def send(msg):
            sent_messages.append(msg)
        async def receive():
            return {"type": "http.request"}

        scope_1 = {
            "type": "http",
            "path": "/health",
            "client": ("198.51.100.55", 12345),
            "headers": [(b"x-forwarded-for", b"1.1.1.1")],
        }
        asyncio.run(mw(scope_1, receive, send))
        # First request allowed
        self.assertEqual(sent_messages[0]["status"], 200)

        # Second request from same peer but claiming a different forwarded IP
        sent_messages_2 = []
        async def send_2(msg):
            sent_messages_2.append(msg)
        scope_2 = {
            "type": "http",
            "path": "/health",
            "client": ("198.51.100.55", 12345),
            "headers": [(b"x-forwarded-for", b"2.2.2.2")],
        }
        asyncio.run(mw(scope_2, receive, send_2))
        # Must be throttled based on peer IP, ignoring the spoofed X-Forwarded-For
        self.assertEqual(sent_messages_2[0]["status"], 429)

    def test_global_heavy_budget_enforced(self):
        limiter = RateLimiter(default_limit=100, heavy_limit=10, window_seconds=60.0, global_heavy_limit=3)
        # 3 different IPs make heavy requests
        self.assertTrue(limiter.is_allowed("10.0.0.1", "/experiments/run")[0])
        self.assertTrue(limiter.is_allowed("10.0.0.2", "/experiments/run")[0])
        self.assertTrue(limiter.is_allowed("10.0.0.3", "/experiments/run")[0])
        # 4th heavy request from a new IP hits the global heavy limit
        allowed, limit, _ = limiter.is_allowed("10.0.0.4", "/experiments/run")
        self.assertFalse(allowed)
        self.assertEqual(limit, 3)

    def test_all_experiment_endpoints_path_traversal_guards(self):
        bad_id = "../../../etc/shadow"
        for endpoint in [
            f"/experiments/{bad_id}",
            f"/experiments/{bad_id}/artifacts",
            f"/experiments/{bad_id}/court-record",
        ]:
            resp = self.client.get(endpoint)
            self.assertIn(resp.status_code, (400, 404))
