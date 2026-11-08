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

A full Ragnarök Gauntlet mission was submitted to the production server:
- Mission ID: `mission-ragnarok-gauntlet`
- World ID: `ragnarok-gauntlet`
- Endpoint: `POST https://domnir.erebuzzz.tech/missions/run`
- Record ID: `mcr-0e4d778a62794d42`
- URL: `https://domnir.erebuzzz.tech/missions/court-records/mcr-0e4d778a62794d42`
- Saved to: `docs/evidence/live_gauntlet_court_record.json`

## 3. Independent Verification: PASS (Authentic)

Command executed:
```bash
python -m domnir.verify live_gauntlet_court_record.json --trusted-key keys.json --model-path .cache/mujoco_menagerie/bitcraze_crazyflie_2/cf2.xml
```

Verifier output:
```text
============================================================
DOMNIR MISSION COURT RECORD VERIFICATION REPORT
Record ID:      mcr-0e4d778a62794d42
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

All 22 cryptographic, schema, physics replay, and verdict checks passed with zero difference (`0.00e+00`). The Ed25519 signature verified as `AUTHENTIC` under pinned key `175a6cdf9b45d248`.

## 4. Tampered Action Verification: FAIL (Rejection Proof)

One controller action in the authentic record was modified by +0.05 (`controller_actions[0][0] += 0.05`), simulating an attacker attempting to forge or tamper with flight telemetry.

Command executed:
```bash
python -m domnir.verify live_gauntlet_court_record_tampered.json --trusted-key keys.json --model-path .cache/mujoco_menagerie/bitcraze_crazyflie_2/cf2.xml
```

Verifier output:
```text
============================================================
DOMNIR MISSION COURT RECORD VERIFICATION REPORT
Record ID:      mcr-0e4d778a62794d42
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
[FAIL] world_hash
[PASS] faults_hash
[FAIL] world_registry
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
     - ERROR: World spec SHA-256 mismatch
     - ERROR: World geometry differs from the registered 'ragnarok-gauntlet' world
     - ERROR: Integration-state checkpoints diverged from replay (max difference 9.87e+00)
     - ERROR: Recorded trajectory samples do not match the replayed flight
     - ERROR: Recorded contact history does not match the replayed flight
     - ERROR: Recorded stage results do not match the replayed flight
============================================================
```

The verifier detected the tampering at every layer:
1. `content_hash` failed immediately: the SHA-256 seal mismatch proved the record was modified after signing.
2. Independent physics replay diverged by `9.87e+00`.
3. Checkpoints, trajectory samples, contacts, and stage results all failed against re-flown physics.
Overall result: `FAIL`.
