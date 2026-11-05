# Privacy Policy

## 1. Overview

Domnir is an open source adversarial falsification platform for robotics research. We respect your privacy and are committed to transparent, minimal data processing.

## 2. Information Handled by Domnir

### 2.1 Flight Specifications and Controller Code
When you submit a flight specification or generate a flight controller via the Domnir interface or API:
- The specification (target altitude, disturbance force limits, mission duration) is processed in memory to validate bounds and parameterize simulation trials.
- AI controller generation queries Vultr Serverless Inference (`https://api.vultrinference.com/v1`). Only the prompt and structural specification schema are sent to the inference endpoint.
- Serverless inference credentials (API keys) are kept server-side only and are never sent to the web browser or guest sandboxes.

### 2.2 Ephemeral Sandbox Isolation
- Controller execution runs inside disposable microVM guest sandboxes on the host server.
- Sandboxes are transient and destroyed immediately upon simulation completion, timeout, or failure.
- No personal user identifiers, browsing history, or persistent credentials are saved inside guest environments.

### 2.3 Court Records and Event Logs
- Simulation trajectories (position, velocity, thrust commands) and host broker events are compiled into exportable Court Record JSON packages.
- Court Records contain purely technical physical telemetry and SHA-256 cryptographic hashes.
- No personal identity data or tracking cookies are embedded in Court Records.

### 2.4 Browser Analytics and Tracking
- The Domnir web application contains zero third-party tracking scripts, zero advertising trackers, and zero external CDN analytics.
- All styles, scripts, and fonts are self-hosted with zero external runtime network dependencies.
- Local browser storage (session storage) is used solely for transient UI state during active experiments.

## 3. Data Retention
- In-memory simulation jobs and Court Records persist only for the duration of the server process unless explicitly exported by the operator.
- Host event logs record technical capability decisions and execution timestamps for auditability without capturing personal user data.

## 4. Updates to This Policy
Any updates to this policy will be documented directly in this repository.
