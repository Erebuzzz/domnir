# Security Policy

## 1. Scope and Blast Radius Zero Model

Domnir is an adversarial falsification and containment platform for AI-generated drone flight control code. It is designed from the ground up under the Blast Radius Zero threat model:

1. Generated controller code is considered completely untrusted.
2. The host system must never execute generated controller code directly.
3. MicroVM sandboxes are default-deny, ephemeral, isolated from external networks, and given zero host mount points or secrets.
4. Host capability requests are denied by deterministic broker logic.
5. All physical plant updates and safety metrics are computed exclusively on the trusted host simulation harness.

## 2. Reporting Security Vulnerabilities

We take containment bypasses and security vulnerabilities seriously. If you identify a potential security vulnerability or containment escape, please report it responsibly:

- Email the project maintainers directly or open a confidential security advisory on GitHub.
- Please do not submit public issues or disclose details until maintainers have had an opportunity to review, reproduce, and address the issue.
- Include detailed steps to reproduce the issue, including the controller code, configuration, environment details, and observed host impact.

### Security Response Commitments
- Acknowledge receipt of vulnerability reports within 48 hours.
- Provide an initial technical assessment and reproduction confirmation within 5 business days.
- Coordinate a responsible disclosure timeline and patch release.

## 3. Supported Versions

Only the current main branch and latest released tagged versions receive active security updates:

| Version | Supported |
| :--- | :--- |
| main (0.1.0) | Yes |
| < 0.1.0 | No |

## 4. Non-Negotiable Trust Boundaries

The following design constraints are intentional security boundaries:

- No Guest Secret Access: Vultr API keys, credentials, host sockets, and filesystem roots are never exposed to guest microVMs.
- No Direct Host Execution: Any test or runtime configuration that bypasses microVM isolation to run untrusted code on the host is considered a critical security violation.
- Strict Resource Limits: Every guest execution is bounded by wall-clock watchdogs (default 0.50 s), memory limits (default 512 MiB), and CPU restrictions.
- Cryptographic Integrity: Trajectories, actions, models, and host events are sealed using SHA-256 digests. Tampered evidence or modified event chains are explicitly rejected.
