# Offline Court Record Verification Proof

This evidence documents the offline, multi-tier independent verification of a live Court Record produced by Dómnir against the pinned server Ed25519 provenance key.

## 1. Provenance Key Verification

Endpoint: `GET https://domnir.erebuzzz.tech/provenance/keys`
Saved to: `docs/evidence/keys.json`

```json
{
  "keys": [
    {
      "key_id": "175a6cdf9b45d248",
      "public_key": "QojO283tOdUx6c/RdiAH/esn7wxRw0OqhzUoBAPsk04=",
      "algorithm": "Ed25519",
      "ephemeral": false
    }
  ],
  "note": "Pin this key to verify records offline: python -m domnir.verify record.json --trusted-key <public_key>"
}
```

## 2. Live Mission Court Record

A full Gauntlet mission was submitted to the production server:
- Mission ID: `mission-open-field`
- Preset ID: `gauntlet`
- Endpoint: `POST https://domnir.erebuzzz.tech/missions/run`
- Record ID: `mcr-c410b3a9bfed43bd`
- URL: `https://domnir.erebuzzz.tech/missions/court-records/mcr-c410b3a9bfed43bd`
- Portable Scene Fingerprint: `b0e1ffffb41b81334870ad9d7d06453b7e4e014cd18c9d19b26f0a277124d5f2`
- Saved to: `docs/evidence/live_gauntlet_court_record.json`

## 3. Independent Verification: PASS (Authentic)

Command executed on an independent machine from a relocated model path:
```bash
python -m domnir.verify docs/evidence/live_gauntlet_court_record.json \
    --trusted-key docs/evidence/keys.json \
    --model-path .cache/mujoco_menagerie/bitcraze_crazyflie_2/cf2.xml
```

Verifier output:
```text
============================================================
DOMNIR MISSION COURT RECORD VERIFICATION REPORT
Record ID:      mcr-c410b3a9bfed43bd
Mission ID:     mission-open-field
Overall Result: PASS
Replay:         MATCHED (max diff 0.00e+00)
Authenticity:   AUTHENTIC (signer key 175a6cdf9b45d248)
============================================================
[PASS] content_hash
[PASS] record_signature
[PASS] provenance
[PASS] schema
[PASS] mission_hash
[PASS] world_hash
[PASS] faults_hash
[PASS] world_registry
[PASS] controller_hash
[PASS] event_chain
[PASS] limitations
[PASS] qualification
[PASS] model_hashes
[PASS] integration_signature
[PASS] compiled_mjcf
[PASS] controller_rate
[PASS] replay
[PASS] checkpoints
[PASS] trajectory_samples
[PASS] contacts
[PASS] stage_results
[PASS] verdicts
============================================================
```

All 22 cryptographic, schema, physics replay, and verdict checks passed with zero difference (`0.00e+00`). The Ed25519 signature verified as `AUTHENTIC` under pinned key `175a6cdf9b45d248`. Because the record carries `compiled_mjcf_portable_sha256`, the compiled scene verification succeeds regardless of the host model checkout directory.

When run without pinning the trusted key:
- Authenticity is reported as `SIGNED_UNTRUSTED_KEY (signer key 175a6cdf9b45d248)`.
- All 22 deterministic integrity checks pass, noting that the key must be pinned to confirm issuer identity.

## 4. Tampered Action Verification: FAIL (Rejection Proof)

One controller action in the authentic record was modified by +0.05 (`controller_actions[0][0] += 0.05`), simulating an attacker attempting to forge or tamper with flight telemetry.

Command executed:
```bash
python -m domnir.verify docs/evidence/live_gauntlet_court_record_tampered.json \
    --trusted-key docs/evidence/keys.json \
    --model-path .cache/mujoco_menagerie/bitcraze_crazyflie_2/cf2.xml
```

Verifier output:
```text
============================================================
DOMNIR MISSION COURT RECORD VERIFICATION REPORT
Record ID:      mcr-c410b3a9bfed43bd
Mission ID:     mission-open-field
Overall Result: FAIL
Replay:         DIVERGED (max diff 1.09e-02)
Authenticity:   AUTHENTIC (signer key 175a6cdf9b45d248)
============================================================
[FAIL] content_hash
[PASS] record_signature
[PASS] provenance
[PASS] schema
[PASS] mission_hash
[PASS] world_hash
[PASS] faults_hash
[PASS] world_registry
[PASS] controller_hash
[PASS] event_chain
[PASS] limitations
[PASS] qualification
[PASS] model_hashes
[PASS] integration_signature
[PASS] compiled_mjcf
[PASS] controller_rate
[PASS] replay
[FAIL] checkpoints
[FAIL] trajectory_samples
[PASS] contacts
[FAIL] stage_results
[PASS] verdicts
     - ERROR: Record content SHA-256 does not match; the record was modified after it was sealed
     - ERROR: Integration-state checkpoints diverged from replay (max difference 1.09e-02)
     - ERROR: Recorded trajectory samples do not match the replayed flight
     - ERROR: Recorded stage results do not match the replayed flight
============================================================
```

The verifier detected the tampering across layers:
1. `content_hash` failed: the SHA-256 seal mismatch proved the record was modified after signing.
2. Independent physics replay diverged by `1.09e-02`.
3. Checkpoints, trajectory samples, and stage results all failed against re-flown physics.
Overall result: `FAIL`.
