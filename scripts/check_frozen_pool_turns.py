"""Offline coverage scan of every frozen-team move instance and one switch per lead."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
import time
import tomllib

if __package__:
    from .check_damage_conformance import ROOT, PINS, digest, tree_hash, verify_engine_wheel
    from .check_joint_turns import comparable, key, mapped_state, native_projection, to_id
else:
    from check_damage_conformance import ROOT, PINS, digest, tree_hash, verify_engine_wheel
    from check_joint_turns import comparable, key, mapped_state, native_projection, to_id

# These require additional state/history projections, even if present HP happens to agree.
UNCHECKED = {
    "futuresight": "delayed attack counter/source", "wish": "delayed heal counter",
    "encore": "move lock/duration", "gigatonhammer": "last-move restriction",
    "firstimpression": "turns on field", "rest": "sleep counter", "sleeptalk": "called-move/sleep history",
    "saltcure": "persistent residual", "psychicnoise": "heal-block duration", "infestation": "trapping duration",
    "roost": "temporary typing", "defog": "terrain/screens beyond hazard projection",
    "courtchange": "non-hazard side conditions", "tripleaxel": "multi-hit/accuracy distribution",
    "dragondarts": "multi-hit distribution", "whirlwind": "phazing distribution",
    "voltswitch": "pivot continuation", "uturn": "pivot continuation", "flipturn": "pivot continuation",
    "partingshot": "pivot continuation", "chillyreception": "pivot/weather continuation",
}
WEATHER = {"": None, "sunnyday": "Sun", "raindance": "Rain", "sandstorm": "Sand", "snowscape": "Snow"}


def pool_records(manifest_path, directory):
    manifest = tomllib.loads(manifest_path.read_text())
    records = []
    for entry in manifest["teams"]:
        path = directory / entry["file"]
        if digest(path) != entry["sha256"]:
            raise ValueError("Frozen team hash mismatch: " + entry["file"])
        records.append({"file": entry["file"], "sha256": entry["sha256"], "export": path.read_text()})
    return manifest, records


def jobs_for(teams):
    return [{"id": f"{team['file']}/lead{lead + 1}/" + (f"move{move + 1}" if move is not None else "switch2"),
             "team": ti, "lead": lead, "move": move}
            for ti, team in enumerate(teams) for lead, member in enumerate(team["sets"])
            for move in [*range(len(member["moves"])), None]]


def main():
    from poke_engine import generate_instructions
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "config/team_pools/gen9ou_control_v1.toml")
    parser.add_argument("--team-directory", type=Path, default=ROOT / ".artifacts/metamon/teams/competitive/gen9ou")
    parser.add_argument("--engine-wheel", type=Path, default=ROOT / ".artifacts/conformance/engine/jointfix-v1/poke_engine-0.0.48-cp312-cp312-manylinux_2_34_x86_64.whl")
    parser.add_argument("--seeds", type=int, default=4)
    parser.add_argument("--limit", type=int, help="Diagnostic subset, not full pool coverage")
    parser.add_argument("--oracle-report", type=Path, help="Reuse hash-checked saved Showdown outcomes, not new coverage")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or not 1 <= args.seeds <= 64 or (args.limit is not None and args.limit < 1):
        parser.error("new output, positive limit and 1..64 seeds required")
    artifact = verify_engine_wheel(args.engine_wheel, "jointfix-v1")
    showdown = ROOT / "pokemon-showdown"
    if subprocess.check_output(["git", "-C", str(showdown), "rev-parse", "HEAD"], text=True).strip() != PINS["showdown"]:
        raise ValueError("Showdown revision differs")
    dirty = subprocess.check_output(["git", "-C", str(showdown), "status", "--short"], text=True).splitlines()
    if dirty not in ([], [" M package-lock.json"]):
        raise ValueError("Unreviewed Showdown source edits")
    compiled = tree_hash((str(p.relative_to(showdown)), p) for d in ("dist/sim", "dist/data")
                         for p in (showdown / d).rglob("*.js"))
    verified = json.loads((ROOT / ".artifacts/conformance/damage/jointfix_v2_regression.json").read_text())
    if compiled != verified["compiled_oracles"]["showdown"]:
        raise ValueError("Compiled oracle differs")
    manifest, records = pool_records(args.manifest, args.team_directory)
    command = ["node", str(ROOT / "scripts/frozen_pool_oracle.cjs"), str(showdown)]
    inventory = json.loads(subprocess.check_output(command, input=json.dumps({"mode": "inventory", "teams": records}), text=True))
    all_jobs = jobs_for(inventory["teams"])
    jobs = all_jobs[:args.limit] if args.limit is not None else all_jobs
    seeds = [[63, n, 41, 29] for n in range(1, args.seeds + 1)]
    cached_sha = None
    if args.oracle_report:
        prior = json.loads(args.oracle_report.read_text())
        for field, expected in (("manifest_sha256", digest(args.manifest)), ("compiled_showdown", compiled),
                                ("oracle_sha256", digest(ROOT / "scripts/frozen_pool_oracle.cjs")),
                                ("shared_oracle_sha256", digest(ROOT / "scripts/joint_turn_oracle.cjs")), ("seeds", seeds)):
            if prior[field] != expected:
                raise ValueError("Cached oracle provenance differs: " + field)
        if [r["job"] for r in prior["cases"]] != jobs:
            raise ValueError("Cached jobs differ")
        oracles = [{"id": r["job"]["id"], "sets": r["fixture"]["teams"], "outcomes": r["showdown_outcomes"]} for r in prior["cases"]]
        cached_sha, oracle_seconds = digest(args.oracle_report), None
    else:
        start = time.perf_counter()
        oracles = json.loads(subprocess.check_output(command, input=json.dumps({"mode": "turns", "teams": records,
                                    "jobs": jobs, "seeds": seeds}), text=True))
        oracle_seconds = time.perf_counter() - start
    rows, latencies = [], []
    for job, oracle in zip(jobs, oracles, strict=True):
        if job["id"] != oracle["id"]:
            raise ValueError("Oracle job order differs")
        initial = oracle["outcomes"][0]
        before, field = initial["before"], initial["field_before"]
        if any(o["before"] != before or o["field_before"] != field for o in oracle["outcomes"]):
            raise ValueError("Seed-dependent entry state needs another mapping")
        fixture = {"id": job["id"], "teams": oracle["sets"], "weather": WEATHER[field["weather"]],
                   "weather_turns": field["weather_turns"], "hazards": [{}, {}]}
        action = to_id(oracle["sets"][0][0]["moves"][job["move"]]) if job["move"] is not None else "switch"
        opponent_action = to_id(oracle["sets"][1][0]["moves"][0])
        unchecked = {move: UNCHECKED[move] for move in (action, opponent_action) if move in UNCHECKED}
        row = {"job": job, "action": action, "opponent_action": opponent_action, "fixture": fixture,
               "showdown_outcomes": oracle["outcomes"], "unchecked_mechanics": unchecked,
               "actor_move_observed": sum(any(l.startswith('|move|p1a: side1slot1|') for l in o['log'])
                                          for o in oracle["outcomes"]) if job["move"] is not None else None}
        unsupported = sorted(set(v for side in initial["initial_volatiles"] for v in side))
        if unsupported or field["terrain"]:
            row.update(classification="unsupported_initial_state", reason={"volatiles": unsupported, "terrain": field["terrain"]})
            rows.append(row)
            continue
        try:
            state = mapped_state(fixture, before)
            sizes = tuple(len(team) for team in oracle["sets"])
            counts = [[len(spec["moves"]) for spec in team] for team in oracle["sets"]]
            if comparable(before) != native_projection(state, sizes, counts):
                raise ValueError("Initial projected mapping differs")
            state_string = state.to_string()
            native_action = action if action != "switch" else to_id(oracle["sets"][0][1]["species"])
            start = time.perf_counter_ns()
            branches = generate_instructions(state, native_action, opponent_action)
            latencies.append((time.perf_counter_ns() - start) / 1000)
            if not branches or any(not math.isfinite(b.percentage) or b.percentage < 0 for b in branches) or not math.isclose(sum(b.percentage for b in branches), 100, abs_tol=1e-3):
                raise ValueError("Invalid branch weights")
            outcomes = []
            for branch in branches:
                after = state.apply_instructions(branch)
                if state.to_string() != state_string or after.reverse_instructions(branch).to_string() != state_string:
                    raise ValueError("Mutating/non-reversible native branch")
                outcomes.append({"probability": branch.percentage / 100,
                                 "after": native_projection(after, sizes, counts),
                                 "force_switch": [after.side_one.force_switch, after.side_two.force_switch],
                                 "instructions": [repr(i) for i in branch.instruction_list]})
            full = {key(o["after"]) for o in outcomes}
            nonhp = {key(comparable(o["after"], hp=False)) for o in outcomes}
            sampled = {key(comparable(o["after"])) for o in oracle["outcomes"]}
            sampled_nonhp = {key(comparable(o["after"], hp=False)) for o in oracle["outcomes"]}
            classification = ("sampled_projection_support_agrees" if sampled <= full else
                              "hp_only_sampled_support_difference" if sampled_nonhp <= nonhp else "non_hp_sampled_support_difference")
            row.update(classification=classification, engine_outcomes=outcomes,
                       initial_engine_state_sha256=hashlib.sha256(state_string.encode()).hexdigest())
        except BaseException as error:
            # PyO3 reports a caught Rust unwind as PanicException, not Exception.
            # Preserve interrupts/exits; an unsupported engine state must stay in the report.
            if not isinstance(error, Exception) and type(error).__name__ != "PanicException":
                raise
            row.update(classification="mapping_or_engine_error", reason=str(error))
        rows.append(row)
    report = {"schema_version": 1, "manifest": manifest, "manifest_sha256": digest(args.manifest),
              "teams": [{k: v for k, v in r.items() if k != "export"} for r in records],
              "inventory": inventory["inventory"], "engine_artifact": artifact,
              "showdown_revision": PINS["showdown"], "compiled_showdown": compiled,
              "runner_sha256": digest(Path(__file__)), "oracle_sha256": digest(ROOT / "scripts/frozen_pool_oracle.cjs"),
              "shared_oracle_sha256": digest(ROOT / "scripts/joint_turn_oracle.cjs"),
              "mapping_helper_sha256": digest(ROOT / "scripts/check_joint_turns.py"),
              "damage_mapping_helper_sha256": digest(ROOT / "scripts/check_damage_conformance.py"),
              "cached_oracle_report_sha256": cached_sha,
              "seeds": seeds, "planned_jobs": len(all_jobs), "full_pool_scan": len(jobs) == len(all_jobs),
              "classification_counts": dict(Counter(r["classification"] for r in rows)), "cases": rows,
              "engine_query_us": {"count": len(latencies), "median": statistics.median(latencies) if latencies else None,
                                  "max": max(latencies) if latencies else None}, "oracle_seconds": oracle_seconds,
              "gate_passed": False,
              "limits": ["first-turn controlled low-PP probes, not 10000 reachable transitions or full games",
                         "subset final projection; no delayed/volatile/continuation certification",
                         "finite sampled support is not exact stochastic probability comparison",
                         "actual pinned local OU teams, not PokéAgent server legality; team redistribution rights unresolved",
                         "no live integration or competitive strength claim"]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"jobs": len(rows), "planned_jobs": len(all_jobs), "inventory": {k: len(v) for k, v in inventory["inventory"].items()},
                      "classification_counts": report["classification_counts"], "output": str(args.output)}))


if __name__ == "__main__":
    main()
