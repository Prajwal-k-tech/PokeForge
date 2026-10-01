"""Fail-closed paired audit of baseline/variant damage reports on identical oracle fixtures."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path


def compare_cases(baseline, variant):
    if len(baseline) != len(variant) or not baseline:
        raise ValueError("different or empty case counts")
    changes = []
    ids = set()
    for before, after in zip(baseline, variant, strict=True):
        case_id = before["fixture"]["id"]
        if case_id in ids:
            raise ValueError("duplicate fixture ID")
        ids.add(case_id)
        for field in ("fixture", "engine_state_sha256"):
            if before[field] != after[field]:
                raise ValueError(f"input mismatch: {case_id} {field}")
        for field in ("showdown", "smogon_calc", "state", "calc_stats", "seed"):
            if before["oracle"][field] != after["oracle"][field]:
                raise ValueError(f"oracle mismatch: {case_id} {field}")
        if before["oracle"]["showdown"] != before["oracle"]["smogon_calc"]:
            raise ValueError(f"oracles disagree: {case_id}")
        expected = [max(before["oracle"]["showdown"][k]) for k in ("regular", "critical")]
        for row in (before, after):
            if row["engine_maximum_agreement"] != (row["engine_maxima"] == expected):
                raise ValueError("inconsistent stored agreement label")
        old_error = [abs(d - e) for d, e in zip(before["engine_maxima"], expected, strict=True)]
        new_error = [abs(d - e) for d, e in zip(after["engine_maxima"], expected, strict=True)]
        if any(n > o for o, n in zip(old_error, new_error, strict=True)):
            raise ValueError(f"maximum damage error worsened: {case_id}")
        if before["engine_maxima"] != after["engine_maxima"]:
            changes.append({"case_id": case_id, "before": before["engine_maxima"],
                            "after": after["engine_maxima"], "oracle_maxima": expected,
                            "absolute_error_before": old_error, "absolute_error_after": new_error})
    return {"cases": len(ids), "changed": len(changes), "unchanged": len(ids) - len(changes),
            "changes": changes,
            "baseline_exact_maximum_pairs": sum(r["engine_maximum_agreement"] for r in baseline),
            "variant_exact_maximum_pairs": sum(r["engine_maximum_agreement"] for r in variant),
            "baseline_classifications": dict(Counter(r["classification"] for r in baseline)),
            "variant_classifications": dict(Counter(r["classification"] for r in variant)),
            "scope": "no worsening of maximum absolute error on this fixture set only; not full rolls/transitions/strength"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--variant", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    baseline, variant = [json.loads(p.read_text()) for p in (args.baseline, args.variant)]
    if baseline["engine_artifact"]["variant"] != "baseline" or variant["engine_artifact"]["variant"] != "critstats-v1":
        raise ValueError("wrong labeled pair of engine variants")
    for field in ("pins", "expanded_fixtures_sha256", "node_oracle_sha256", "compiled_oracles"):
        if baseline[field] != variant[field]:
            raise ValueError(f"report provenance mismatch: {field}")
    result = compare_cases(baseline["cases"], variant["cases"])
    result |= {"schema_version": 1, "gate_passed": False,
               "inputs": {"baseline_sha256": hashlib.sha256(args.baseline.read_bytes()).hexdigest(),
                          "variant_sha256": hashlib.sha256(args.variant.read_bytes()).hexdigest()},
               "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        stream.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "changes"}, indent=2))


if __name__ == "__main__":
    main()
