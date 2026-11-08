"""Security middleware and helpers for Dómnir API."""

from __future__ import annotations

import os
import re
import threading
import time
from collections import defaultdict
from typing import Any, Callable
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

MAX_REQUEST_BYTES = 65536  # 64 KiB general limit
MAX_COURT_RECORD_BYTES = 8388608  # 8 MiB: mission records carry every controller action plus state checkpoints
MAX_CODE_BYTES = 32768     # 32 KiB for code payloads

SAFE_ID_PATTERN = re.compile(r"^[0-9a-zA-Z\-_]{1,64}$")


class PayloadTooLargeError(HTTPException):
    def __init__(self, max_bytes: int):
        super().__init__(
            status_code=413,
            detail=f"Request body exceeds limit of {max_bytes} bytes",
        )


def validate_id_param(value: str, param_name: str = "id") -> str:
    """Ensure identifiers contain only safe characters and cannot traverse paths."""
    if not value or not isinstance(value, str) or not SAFE_ID_PATTERN.fullmatch(value) or ".." in value or "/" in value or "\\" in value:
        raise ValueError(f"Malformed {param_name}: invalid character sequence")
    return value


class SecurityHeadersMiddleware:
    """Add defensive security headers to all HTTP responses."""

    def __init__(self, app: Any):
        self.app = app
        self._headers: list[tuple[bytes, bytes]] = [
            (b"x-content-type-options", b"nosniff"),
            (b"x-frame-options", b"DENY"),
            (b"x-xss-protection", b"1; mode=block"),
            (b"referrer-policy", b"strict-origin-when-cross-origin"),
            (
                b"permissions-policy",
                b"accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
                b"magnetometer=(), microphone=(), payment=(), usb=()",
            ),
            (
                b"content-security-policy",
                b"default-src 'self'; "
                b"img-src 'self' data:; "
                b"style-src 'self' 'unsafe-inline'; "
                b"script-src 'self' 'unsafe-inline'; "
                b"connect-src 'self';",
            ),
        ]

    async def __call__(self, scope: dict[str, Any], receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                for key, val in self._headers:
                    headers.append((key, val))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


class RequestSizeLimitMiddleware:
    """Reject requests with bodies larger than the maximum allowed payload."""

    def __init__(
        self,
        app: Any,
        max_bytes: int = MAX_REQUEST_BYTES,
        max_court_record_bytes: int = MAX_COURT_RECORD_BYTES,
    ):
        self.app = app
        self.max_bytes = max_bytes
        self.max_court_record_bytes = max_court_record_bytes

    async def __call__(self, scope: dict[str, Any], receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        effective_limit = (
            self.max_court_record_bytes
            if "/court-records" in path
            else self.max_bytes
        )

        headers = dict(scope.get("headers", []))
        content_length_raw = headers.get(b"content-length")

        if content_length_raw is not None:
            try:
                length = int(content_length_raw.decode("ascii"))
                if length < 0:
                    response = JSONResponse(
                        status_code=400,
                        content={"detail": "Invalid Content-Length header"},
                    )
                    await response(scope, receive, send)
                    return
                if length > effective_limit:
                    response = JSONResponse(
                        status_code=413,
                        content={"detail": f"Request body exceeds limit of {effective_limit} bytes"},
                    )
                    await response(scope, receive, send)
                    return
            except (ValueError, UnicodeDecodeError):
                response = JSONResponse(
                    status_code=400,
                    content={"detail": "Invalid Content-Length header"},
                )
                await response(scope, receive, send)
                return

        received_bytes = 0

        async def limited_receive() -> dict[str, Any]:
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                body = message.get("body", b"")
                received_bytes += len(body)
                if received_bytes > effective_limit:
                    raise PayloadTooLargeError(effective_limit)
            return message

        await self.app(scope, limited_receive, send)


class RateLimiter:
    """Thread-safe sliding-window rate limiter per client IP and global server budget."""

    def __init__(
        self,
        default_limit: int = 120,
        heavy_limit: int = 30,
        window_seconds: float = 60.0,
        global_heavy_limit: int = 120,
    ):
        self.default_limit = default_limit
        self.heavy_limit = heavy_limit
        self.window_seconds = window_seconds
        self.global_heavy_limit = global_heavy_limit
        self._lock = threading.Lock()
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._heavy_requests: dict[str, list[float]] = defaultdict(list)
        self._global_heavy_requests: list[float] = []
        self._heavy_paths = {
            "/experiments/run",
            "/controllers/generate",
            "/containment/run",
            "/missions/run",
        }
        self._heavy_prefixes = (
            "/ragnarok/",
            "/guardian/",
            "/uncertainty/",
            "/ci/",
            "/missions/",
        )

    def is_allowed(self, client_ip: str, path: str) -> tuple[bool, int, float]:
        with self._lock:
            now = time.monotonic()
            cutoff = now - self.window_seconds
            is_heavy = (
                path in self._heavy_paths
                or any(path.startswith(prefix) for prefix in self._heavy_prefixes)
            )

            # Prune expired timestamps
            self._requests[client_ip] = [t for t in self._requests[client_ip] if t > cutoff]
            if is_heavy or client_ip in self._heavy_requests:
                self._heavy_requests[client_ip] = [
                    t for t in self._heavy_requests[client_ip] if t > cutoff
                ]
            if is_heavy:
                self._global_heavy_requests = [
                    t for t in self._global_heavy_requests if t > cutoff
                ]

            # Check general limit first (all requests count toward default_limit)
            if len(self._requests[client_ip]) >= self.default_limit:
                retry_after = max(1.0, self.window_seconds - (now - self._requests[client_ip][0]))
                return False, self.default_limit, retry_after

            # Check per-client heavy limit if path is heavy
            if is_heavy and len(self._heavy_requests[client_ip]) >= self.heavy_limit:
                retry_after = max(
                    1.0, self.window_seconds - (now - self._heavy_requests[client_ip][0])
                )
                return False, self.heavy_limit, retry_after

            # Check global heavy budget limit across all clients
            if is_heavy and len(self._global_heavy_requests) >= self.global_heavy_limit:
                retry_after = max(
                    1.0, self.window_seconds - (now - self._global_heavy_requests[0])
                )
                return False, self.global_heavy_limit, retry_after

            # Record allowed request
            self._requests[client_ip].append(now)
            if is_heavy:
                self._heavy_requests[client_ip].append(now)
                self._global_heavy_requests.append(now)

            limit = self.heavy_limit if is_heavy else self.default_limit
            return True, limit, 0.0


class RateLimitMiddleware:
    """Enforce rate limits on incoming HTTP requests with proxy trust boundaries."""

    def __init__(
        self,
        app: Any,
        limiter: RateLimiter | None = None,
        enforce_testclient: bool = False,
    ):
        self.app = app
        self.limiter = limiter or RateLimiter()
        self.enforce_testclient = enforce_testclient
        self.disabled = os.environ.get("DOMNIR_DISABLE_RATE_LIMIT") == "1"

    async def __call__(self, scope: dict[str, Any], receive: Callable, send: Callable) -> None:
        if scope["type"] != "http" or self.disabled:
            await self.app(scope, receive, send)
            return

        client = scope.get("client")
        peer_ip = client[0] if client else "unknown"

        # Only trust forwarded headers if immediate peer is a configured reverse proxy or loopback
        trusted_proxies_env = os.environ.get("DOMNIR_TRUSTED_PROXIES", "127.0.0.1,::1,localhost,testclient")
        trusted_proxies = {p.strip() for p in trusted_proxies_env.split(",") if p.strip()}
        trust_forwarded = (peer_ip in trusted_proxies) or (os.environ.get("DOMNIR_TRUST_ALL_PROXIES") == "1")

        client_ip = peer_ip
        if trust_forwarded:
            headers = dict(scope.get("headers", []))
            cf_ip = headers.get(b"cf-connecting-ip")
            if cf_ip:
                client_ip = cf_ip.decode("latin1").strip()
            else:
                forwarded = headers.get(b"x-forwarded-for")
                if forwarded:
                    client_ip = forwarded.decode("latin1").split(",")[0].strip()

        if client_ip in {"testclient", "test"} and not self.enforce_testclient:
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        allowed, limit, retry_after = self.limiter.is_allowed(client_ip, path)
        if not allowed:
            response = JSONResponse(
                status_code=429,
                content={"detail": f"Too many requests. Limit is {limit} requests per minute."},
                headers={"Retry-After": str(int(retry_after))},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
