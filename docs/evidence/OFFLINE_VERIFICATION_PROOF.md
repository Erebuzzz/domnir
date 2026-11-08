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

## 2. Live Ragnarök Gauntlet Court Record

A full Ragnarök Gauntlet mission was submitted to the production server:
- Mission ID: `mission-ragnarok-gauntlet`
- World ID: `ragnarok-gauntlet`
- Stages: `takeoff`, `slalom_pillar`, `transit_gate`, `approach_pad`, `precision_touchdown` (5 stages)
- Endpoint: `POST https://domnir.erebuzzz.tech/missions/run` with `{"world_id": "ragnarok-gauntlet"}`
- Record ID: `mcr-5d9ab54b8ee34430`
- URL: `https://domnir.erebuzzz.tech/missions/court-records/mcr-5d9ab54b8ee34430`
- Portable Scene Fingerprint: `b827522d86a2101d2ed58aefc8a9af02880e31381e366b18843b0bc4fc913b7e`
- Saved to: `docs/evidence/live_gauntlet_court_record.json`

## 3. Independent Verification: PASS (Authentic)

Command executed on an independent machine from a relocated model path:
```bash
python -m domnir.verify docs/evidence/live_gauntlet_court_record.json \
    --trusted-key docs/evidence/keys.json \
    --model-path <relocated_cf2.xml>
```

Verifier output:
```text
============================================================
DOMNIR MISSION COURT RECORD VERIFICATION REPORT
Record ID:      mcr-5d9ab54b8ee34430
Mission ID:     mission-ragnarok-gauntlet
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
    --model-path <relocated_cf2.xml>
```

Verifier output:
```text
============================================================
DOMNIR MISSION COURT RECORD VERIFICATION REPORT
Record ID:      mcr-5d9ab54b8ee34430
Mission ID:     mission-ragnarok-gauntlet
Overall Result: FAIL
Replay:         DIVERGED (max diff 9.87e+00)
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
[FAIL] contacts
[FAIL] stage_results
[PASS] verdicts
     - ERROR: Record content SHA-256 does not match; the record was modified after it was sealed
     - ERROR: Integration-state checkpoints diverged from replay (max difference 9.87e+00)
     - ERROR: Recorded trajectory samples do not match the replayed flight
     - ERROR: Recorded contact history does not match the replayed flight
     - ERROR: Recorded stage results do not match the replayed flight
============================================================
```

The verifier detected the tampering across layers:
1. `content_hash` failed: the SHA-256 seal mismatch proved the record was modified after signing.
2. Independent physics replay diverged by `9.87e+00`.
3. Checkpoints, trajectory samples, contacts, and stage results all failed against re-flown physics.
Overall result: `FAIL`.
