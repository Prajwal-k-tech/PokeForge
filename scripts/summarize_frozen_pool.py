"""Compact, evidence-derived coverage and mismatch witnesses; never a conformance score."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

if __package__:
    from .check_joint_turns import comparable, key
else:
    from check_joint_turns import comparable, key


def differences(left, right):
    result = []
    for si in range(2):
        for field in ("active_index", "hazards"):
            if left[si][field] != right[si][field]:
                result.append({"path": f"side{si}/{field}", "engine": left[si][field], "showdown": right[si][field]})
        for pi, (lp, rp) in enumerate(zip(left[si]["pokemon"], right[si]["pokemon"], strict=True)):
            for field in rp:
                if lp[field] != rp[field]:
                    result.append({"path": f"side{si}/slot{pi}/{field}", "engine": lp[field], "showdown": rp[field]})
    return result


def summarize(report):
    rows = report["cases"]
    if not report["full_pool_scan"] or len(rows) != report["planned_jobs"] or len({c["job"]["id"] for c in rows}) != len(rows):
        raise ValueError("Incomplete or duplicate pool jobs")
    matrix = []
    for move in report["inventory"]["moves"]:
        selected = [r for r in rows if r["action"] == move and r["job"]["move"] is not None]
        if not selected:
            raise ValueError("Frozen move absent from scheduled coverage: " + move)
        matrix.append({"move": move, "jobs": [r["job"]["id"] for r in selected],
                       "attempt_observations": sum(r["actor_move_observed"] for r in selected),
                       "projection_labels": dict(Counter(r["classification"] for r in selected)),
                       "unchecked_mechanics": sorted(set(v for r in selected for v in r["unchecked_mechanics"].values()))})
    witnesses = []
    for row in rows:
        if "engine_outcomes" not in row:
            continue
        engine = [comparable(o["after"], hp=False) for o in row["engine_outcomes"]]
        support = {key(e) for e in engine}
        misses = [o for o in row["showdown_outcomes"] if key(comparable(o["after"], hp=False)) not in support]
        if (row["classification"] == "non_hp_sampled_support_difference") != bool(misses):
            raise ValueError("Stored non-HP classification disagrees with actual projections")
        if not misses:
            continue
        witness = misses[0]
        expected = comparable(witness["after"], hp=False)
        diffs = min((differences(e, expected) for e in engine), key=len)
        missed_ko = any(witness["after"][si]["pokemon"][pi]["hp"] == 0 and
                        not any(e["after"][si]["pokemon"][pi]["hp"] == 0 for e in row["engine_outcomes"])
                        for si in range(2) for pi in range(6))
        family = ("missing_sampled_KO_support" if missed_ko else
                  "non_ghost_curse_targeting" if row["action"] == "curse" else
                  "defog_evasion_missing" if row["action"] == "defog" else
                  "fixed_damage_contact_effect" if row["action"] == "seismictoss" else
                  "PP_pre_move_prevention" if all(d["path"].endswith("/pp") for d in diffs) else "unadjudicated")
        witnesses.append({"job_id": row["job"]["id"], "seed": witness["seed"], "family": family,
                          "action": row["action"], "opponent_action": row["opponent_action"],
                          "minimum_non_hp_differences": diffs, "missed_sample_count": len(misses),
                          "log": [l for l in witness["log"] if l.startswith(("|move|", "|cant|", "|-status|", "|-boost|", "|-unboost|", "|-start|"))]})
    return {"jobs": len(rows), "move_instance_jobs": sum(r["job"]["move"] is not None for r in rows),
            "switch_jobs": sum(r["job"]["move"] is None for r in rows),
            "seeded_observations": sum(len(r["showdown_outcomes"]) for r in rows),
            "inventory_counts": {k: len(v) for k, v in report["inventory"].items()},
            "classification_counts": dict(Counter(r["classification"] for r in rows)),
            "cases_with_unchecked_mechanics": sum(bool(r["unchecked_mechanics"]) for r in rows),
            "projection_matches_with_unchecked_mechanics": sum(r["classification"] == "sampled_projection_support_agrees" and bool(r["unchecked_mechanics"]) for r in rows),
            "non_hp_witness_families": dict(Counter(w["family"] for w in witnesses)),
            "non_hp_witnesses": witnesses, "move_coverage_matrix": matrix,
            "gate_passed": False,
            "limits": ["classifications are sampled support, not probabilities or ranking",
                       "closest-branch differences are witnesses, not a proof of general causality",
                       "HP discrepancies remain unadjudicated beyond earlier controlled pilots",
                       "unprojected state/continuation can invalidate apparent projection matches",
                       "first-turn low-PP controlled states, not multi-turn reachable-transition conformance"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = summarize(json.loads(args.report.read_text()))
    result.update(schema_version=1, input_sha256=hashlib.sha256(args.report.read_bytes()).hexdigest(),
                  runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps({k: v for k, v in result.items() if k not in ("non_hp_witnesses", "move_coverage_matrix", "limits")}, indent=2))


if __name__ == "__main__":
    main()
