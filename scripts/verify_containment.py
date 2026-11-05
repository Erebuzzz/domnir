"""Check the fixed containment record against its host event chain."""

import argparse
import json
from pathlib import Path

from domnir.containment import verify_containment_record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", type=Path, required=True)
    args = parser.parse_args()
    record = json.loads(args.record.read_text(encoding="utf-8"))
    filename = record["host_event_log"]["file"]
    if Path(filename).name != filename:
        raise ValueError("Invalid host event log name")
    if not verify_containment_record(record, args.record.parent / filename):
        raise ValueError("Containment record and host events do not agree")
    print(
        json.dumps(
            {
                "status": record["status"],
                "host_event_chain_consistent": True,
                "event_chain_signed": False,
                "guest_diagnostics_used_as_host_evidence": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
