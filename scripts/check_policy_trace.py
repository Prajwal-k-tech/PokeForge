"""Audit exact-request, post-clipping probabilities and emitted choices in a local safety trace."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.integration.policy_gate import RequestPolicyGate, restrict_probabilities


def audit_trace(path: Path) -> dict:
    gate = RequestPolicyGate()
    pending_hash = None
    choices, distributions, forced_choices = 0, 0, 0
    removed_total, removed_max = 0.0, 0.0
    for line_number, line in enumerate(path.read_text().splitlines(), 1):
        event = json.loads(line)
        kind = event["event"]
        if kind == "request":
            gate.observe(event["battle_tag"], event["payload"])
            if hashlib.sha256(event["payload"].encode()).hexdigest() != event["request_hash"]:
                raise ValueError(f"request hash mismatch at line {line_number}")
        elif kind == "activate":
            ticket = gate.activate(event["battle_tag"], json.loads(gate.latest_payload))
            if (ticket.request_hash != event["request_hash"] or ticket.rqid != event["rqid"]
                    or list(ticket.legal_mask) != event["legal_mask"]):
                raise ValueError("activation differs from the exact request")
        elif kind == "distribution":
            ticket = gate.current
            if ticket is None or pending_hash is not None or event["request_hash"] != ticket.request_hash:
                raise ValueError("distribution without a matching fresh request")
            gate.validate(ticket, json.loads(gate.latest_payload))
            if event["rqid"] != ticket.rqid or event["battle_tag"] != ticket.battle_tag:
                raise ValueError("distribution has a different request identity")
            expected, removed = restrict_probabilities(event["raw_probabilities"], ticket, event["request_hash"])
            if len(event["legal_probabilities"]) != 13 or not all(
                math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-7)
                for a, b in zip(expected, event["legal_probabilities"], strict=True)
            ) or not math.isclose(removed, event["removed_illegal_mass"], abs_tol=1e-7):
                raise ValueError("recorded probability restriction is incorrect")
            if any(p != 0 for p, legal in zip(event["legal_probabilities"], ticket.legal_mask) if not legal):
                raise ValueError("illegal index retains probability mass")
            pending_hash = ticket.request_hash
            distributions += 1
            removed_total += removed
            removed_max = max(removed_max, removed)
        elif kind == "choice":
            ticket = gate.current
            if ticket is None or event["request_hash"] != pending_hash or ticket.request_hash != pending_hash:
                raise ValueError("choice lacks a matching masked distribution")
            gate.validate(ticket, json.loads(gate.latest_payload))
            if event["rqid"] != ticket.rqid or event["battle_tag"] != ticket.battle_tag:
                raise ValueError("choice has a different request identity")
            if event["wire_command"] != ticket.wire_choice(event["index"]):
                raise ValueError("emitted wire action differs from selected legal semantic action")
            choices += 1
            forced_choices += bool(json.loads(ticket.payload).get("forceSwitch", [False])[0])
            pending_hash = None
        else:
            raise ValueError(f"unexpected/failure event {kind!r} at line {line_number}")
    if not choices or choices != distributions or pending_hash is not None:
        raise ValueError("trace has no choices or an unfinished distribution/choice pair")
    return {"trace_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "choices": choices,
            "forced_switch_choices": forced_choices, "distributions": distributions,
            "removed_illegal_mass_total": removed_total, "removed_illegal_mass_max": removed_max,
            "scope": "recorded action/probability/request consistency, not full state or simulator conformance"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = {"schema_version": 1, "traces": [audit_trace(path) for path in args.log]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        stream.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
