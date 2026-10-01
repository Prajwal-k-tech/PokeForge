"""Fail-closed paired audit of this specific offline engine correction."""
import argparse
import copy
import hashlib
import json
from pathlib import Path

if __package__:
    from .compare_damage_reports import compare_cases
    from .check_joint_turns import comparable
else:
    from compare_damage_reports import compare_cases
    from check_joint_turns import comparable


def compare_turns(before, after):
    if len(before) != 19 or len(after) != 19:
        raise ValueError("Expected the complete 19-case paired control set")
    if len({c["fixture"]["id"] for c in before}) != 19:
        raise ValueError("Duplicate control IDs")
    corrected = {"recover_and_burn", "contact_helmet", "contact_helmet_attacker_faster", "contact_helmet_attacker_slower"}
    changed = []
    for old, new in zip(before, after, strict=True):
        case = old["fixture"]["id"]
        if ({"weather": None} | old["fixture"]) != new["fixture"]:
            raise ValueError("Paired fixture differs: " + case)
        for field in ("initial_engine_state_sha256", "initial_projection"):
            if old[field] != new[field]:
                raise ValueError("Initial mapping differs: " + case)
        if len(old["showdown_outcomes"]) != 64 or not new["engine_outcomes"]:
            raise ValueError("Incomplete paired outcomes")
        for x, y in zip(old["showdown_outcomes"], new["showdown_outcomes"], strict=True):
            for field in ("seed", "before", "after", "turn", "request_state", "ended"):
                if x[field] != y[field]:
                    raise ValueError("Paired oracle differs: " + case)
        if case not in corrected:
            if old["engine_outcomes"] != new["engine_outcomes"]:
                raise ValueError("Unexpected engine outcome change: " + case)
            continue
        for x, y in zip(old["engine_outcomes"], new["engine_outcomes"], strict=True):
            normalized = copy.deepcopy(y["after"])
            normalized[0]["pokemon"][0]["hp"] = x["after"][0]["pokemon"][0]["hp"]
            if normalized != x["after"] or x["probability"] != y["probability"]:
                raise ValueError("Correction changed unrelated state or probability: " + case)
            expected = 227 if case == "recover_and_burn" else 360
            if y["after"][0]["pokemon"][0]["hp"] != expected:
                raise ValueError("Corrected HP differs: " + case)
            if case.startswith("contact_helmet") and sum(i == "Heal SideOne: -72" for i in y["instructions"]) != 1:
                raise ValueError("Expected one exact Helmet activation: " + case)
            if any(o["after"][0]["pokemon"][0]["hp"] != expected for o in new["showdown_outcomes"]):
                raise ValueError("Corrected HP does not match the independent oracle: " + case)
        changed.append(case)
    if set(changed) != corrected:
        raise ValueError("Missing correction controls")
    return {"cases": 19, "changed_cases": changed, "unchanged_cases": 15,
            "scope": "only the diagnosed actor HP changes; other projected state and branch weights unchanged"}


def validate_weather(report):
    expected = {"morning_sun_rounds": 347, "shore_up_rounds": 347, "morning_sun_fixed_point": 536,
                "morning_sun_half_tie_down": 285, "morning_sun_bad_weather_half_tie_down": 192}
    if {c["fixture"]["id"] for c in report["cases"]} != set(expected) or len(report["cases"]) != 5:
        raise ValueError("Missing weather controls")
    for case in report["cases"]:
        if len(case["engine_outcomes"]) != 1 or len(case["showdown_outcomes"]) != 64:
            raise ValueError("Incomplete weather outcomes")
        branch = case["engine_outcomes"][0]
        if branch["probability"] != 1 or branch["after"][0]["pokemon"][0]["hp"] != expected[case["fixture"]["id"]]:
            raise ValueError("Weather recovery differs")
        if any(comparable(o["after"]) != branch["after"] for o in case["showdown_outcomes"]):
            raise ValueError("Weather projections differ from Showdown")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("before", "after", "weather", "direct-before", "direct-after", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    paths = {name: getattr(args, name) for name in ("before", "after", "weather", "direct_before", "direct_after")}
    reports = {name: json.loads(path.read_text()) for name, path in paths.items()}
    for name in ("before", "direct_before"):
        if reports[name]["engine_artifact"]["variant"] != "critstats-v1":
            raise ValueError("Wrong pre-correction variant")
    for name in ("after", "weather", "direct_after"):
        if reports[name]["engine_artifact"]["variant"] != "jointfix-v1":
            raise ValueError("Wrong corrected variant")
        for field in ("wheel_sha256", "native_sha256", "wrapper_sha256"):
            if reports[name]["engine_artifact"][field] != reports["after"]["engine_artifact"][field]:
                raise ValueError("Corrected runtime identity differs")
    if reports["before"]["compiled_showdown"] != reports["after"]["compiled_showdown"]:
        raise ValueError("Showdown executable changed")
    paired = compare_turns(reports["before"]["cases"], reports["after"]["cases"])
    old, new = reports["direct_before"], reports["direct_after"]
    for field in ("pins", "expanded_fixtures_sha256", "node_oracle_sha256"):
        if old[field] != new[field]:
            raise ValueError("Direct oracle/input identity differs")
    for backend in ("showdown", "calc"):
        left, right = [r["compiled_oracles"][backend]["file_sha256"] for r in (old, new)]
        ignored = {"calc/dist/production.min.js", "calc/dist/data/production.min.js"} if backend == "calc" else set()
        if {k: v for k, v in left.items() if k not in ignored} != {k: v for k, v in right.items() if k not in ignored}:
            raise ValueError("Unbundled oracle executable changed")
    direct = compare_cases(old["cases"], new["cases"])
    if direct["changed"]:
        raise ValueError("Transition-only correction changed direct damage")
    weather = reports["weather"]
    validate_weather(weather)
    result = {"schema_version": 1, "joint_correction": paired, "direct_regression": direct,
              "weather_controls": 5, "gate_passed": False,
              "input_sha256": {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()},
              "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "limits": ["same fixed fixture population, not new coverage", "finite seeded projections, not exact stochastic conformance",
                         "calculator unbundled JS unchanged; two unused production bundles were not rebuilt", "not live-integrated"]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print("Verified four corrected controls, fifteen unchanged, five weather controls, and fifty unchanged direct maxima.")


if __name__ == "__main__":
    main()
