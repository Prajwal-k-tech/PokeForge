"""Offline full-turn pilot: pinned Showdown versus a hash-verified engine runtime."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
import time

if __package__:
    from .check_damage_conformance import (
        ROOT, PINS, STATUS, digest, engine_artifact_lock, engine_state, fixtures, tree_hash, verify_engine_wheel,
    )
else:
    from check_damage_conformance import (
        ROOT, PINS, STATUS, digest, engine_artifact_lock, engine_state, fixtures, tree_hash, verify_engine_wheel,
    )

BOOSTS = ("atk", "def", "spa", "spd", "spe", "accuracy", "evasion")
HAZARDS = {"stealthrock": "stealth_rock", "spikes": "spikes",
           "toxicspikes": "toxic_spikes", "stickyweb": "sticky_web"}


def expand(path):
    source = json.loads(path.read_text())
    bases = {f["id"]: f for f in fixtures(path.parent / source["damage_fixtures"])}
    result = []
    for case in source["cases"]:
        base = bases[case["base"]]
        if base["weather"] or base["terrain"] or base["screens"]:
            raise ValueError("This pilot does not translate weather, terrain or screens")
        teams = [[copy.deepcopy(base["attacker"]), copy.deepcopy(bases["physical_against_special_wall"]["defender"])],
                 [copy.deepcopy(base["defender"]), copy.deepcopy(bases["light_ball_special_resisted"]["defender"])]]
        for si, role in enumerate(("attacker", "defender")):
            for field, value in case.get(role + "_override", {}).items():
                if field in ("evs", "ivs", "boosts"):
                    teams[si][0][field].update(value)
                else:
                    teams[si][0][field] = value
        for si, team in enumerate(teams):
            for pi, p in enumerate(team):
                p["name"] = f"side{si + 1}slot{pi + 1}"
                p["moves"] = [case["moves"][si] if pi == 0 else "Splash"]
                p["preTera"] = bool(p["teraType"])
                if not p["teraType"]:
                    p.pop("teraType")
            team[0]["hp"] = case.get("hp", [None, None])[si]
        if "bench_one_item" in case:
            teams[0][1]["item"] = case["bench_one_item"]
        result.append({"id": case["id"], "teams": teams,
                       "actions": case.get("actions", ["move 1", "move 1"]),
                       "hazards": case.get("hazards", [{}, {}]), "weather": case.get("weather")})
    if not result or len({f["id"] for f in result}) != len(result):
        raise ValueError("Expected nonempty, unique fixture IDs")
    return result


def mapped_state(fixture, before):
    from poke_engine import Move, Pokemon, Side, SideConditions, State

    sides = []
    for si in range(2):
        members = []
        for pi, spec in enumerate(fixture["teams"][si]):
            observed = before[si]["pokemon"][pi]
            temp = {"move": spec["moves"][0], "screens": [], "weather": None, "terrain": None}
            side = engine_state(temp, {"attacker": observed, "defender": observed}).side_one
            p = side.pokemon[0]
            members.append(Pokemon(**{name: getattr(p, name) for name in (
                "id", "level", "types", "base_types", "maxhp", "attack", "defense",
                "special_attack", "special_defense", "speed", "ability", "base_ability",
                "item", "nature", "evs", "weight_kg", "status", "terastallized", "tera_type")},
                hp=observed["hp"], moves=[Move(id=to_id(move), pp=observed["pp"][mi])
                                          for mi, move in enumerate(spec["moves"])]))
        boosts = before[si]["pokemon"][0]["boosts"]
        sides.append(Side(pokemon=members, side_conditions=SideConditions(**{
            HAZARDS[k]: v for k, v in fixture["hazards"][si].items()}),
            **dict(zip(("attack_boost", "defense_boost", "special_attack_boost", "special_defense_boost",
                        "speed_boost", "accuracy_boost", "evasion_boost"), (boosts[k] for k in BOOSTS)))))
    return State(side_one=sides[0], side_two=sides[1], weather=(fixture["weather"] or "none").lower(),
                 weather_turns_remaining=fixture.get("weather_turns", 5 if fixture["weather"] else 0))


def to_id(value):
    return "".join(c.lower() for c in value if c.isalnum())


def engine_actions(fixture):
    actions = []
    for si, action in enumerate(fixture["actions"]):
        if action == "move 1":
            actions.append(to_id(fixture["teams"][si][0]["moves"][0]))
        elif action == "switch 2":
            actions.append(to_id(fixture["teams"][si][1]["species"]))
        else:
            raise ValueError("Unsupported action in pilot: " + action)
    return actions


def native_projection(state, team_sizes=(2, 2), move_counts=None):
    statuses = {v: k for k, v in STATUS.items()}
    result = []
    for si, side in enumerate((state.side_one, state.side_two)):
        active = int(side.active_index)
        boosts = [side.attack_boost, side.defense_boost, side.special_attack_boost,
                  side.special_defense_boost, side.speed_boost, side.accuracy_boost, side.evasion_boost]
        # Constructor pads to six slots; project only explicitly supplied members/moves.
        members = []
        for pi, p in enumerate(side.pokemon[:team_sizes[si]]):
            members.append({"species_id": p.id.lower(), "hp": p.hp, "maxhp": p.maxhp,
                            "status": statuses[p.status.lower()] if p.hp else "",
                            "item": "" if p.item.lower() == "none" else p.item.lower(), "ability": p.ability.lower(),
                            "tera_type": p.tera_type.capitalize() if p.terastallized else None,
                            "boosts": dict(zip(BOOSTS, boosts if pi == active and p.hp else [0] * 7)),
                            "pp": [m.pp for m in p.moves[:move_counts[si][pi] if move_counts else 1]]})
        result.append({"active_index": active, "pokemon": members,
                       "hazards": {k: getattr(side.side_conditions, v) for k, v in HAZARDS.items()}})
    return result


def comparable(projection, hp=True):
    result = copy.deepcopy(projection)
    keys = {"species_id", "hp", "maxhp", "status", "item", "ability", "tera_type", "boosts", "pp"}
    if not hp:
        keys.remove("hp")
    for side in result:
        side["pokemon"] = [{k: v for k, v in p.items() if k in keys} for p in side["pokemon"]]
    return result


def key(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def runtime_evidence(report_path, variant, wheel=None):
    import poke_engine
    import poke_engine.poke_engine as native

    if wheel is not None:
        return verify_engine_wheel(wheel, variant) | {"verification": "installed native/wrapper match current locked wheel"}

    prior = json.loads(report_path.read_text())
    artifact = prior["engine_artifact"]
    if artifact["variant"] != variant or artifact["wheel_sha256"] != engine_artifact_lock(variant)["sha256"]:
        raise ValueError("Prior verified wheel evidence has the wrong identity")
    for field, path in (("native_sha256", Path(native.__file__)), ("wrapper_sha256", Path(poke_engine.__file__))):
        if digest(path) != artifact[field]:
            raise ValueError("Installed engine changed since verified wheel comparison")
    return {"variant": variant, "wheel_sha256": artifact["wheel_sha256"],
            "native_sha256": artifact["native_sha256"], "wrapper_sha256": artifact["wrapper_sha256"],
            "verification": "installed files equal saved wheel-verified report; original temporary wheel is not required",
            "prior_verified_report_sha256": digest(report_path)}


def main():
    from poke_engine import generate_instructions

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, default=ROOT / "tests/fixtures/joint_turn_pilot_v1.json")
    parser.add_argument("--showdown", type=Path, default=ROOT / "pokemon-showdown")
    parser.add_argument("--engine-variant", choices=("baseline", "critstats-v1", "jointfix-v1"), default="critstats-v1")
    parser.add_argument("--engine-wheel", type=Path)
    parser.add_argument("--verified-engine-report", type=Path,
                        default=ROOT / ".artifacts/conformance/damage/critical_stats_variant_v2_adjudicated.json")
    parser.add_argument("--seeds", type=int, default=64)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.seeds <= 4096:
        parser.error("--seeds must be between 1 and 4096")
    if args.output.exists():
        parser.error("refusing to overwrite an existing report")
    artifact = runtime_evidence(args.verified_engine_report, args.engine_variant, args.engine_wheel)
    if subprocess.check_output(["git", "-C", str(args.showdown), "rev-parse", "HEAD"], text=True).strip() != PINS["showdown"]:
        raise ValueError("Showdown revision differs from lock")
    dirty = subprocess.check_output(["git", "-C", str(args.showdown), "status", "--short"], text=True).splitlines()
    if dirty not in ([], [" M package-lock.json"]):
        raise ValueError("Unreviewed Showdown source edits")
    compiled = tree_hash((str(p.relative_to(args.showdown)), p)
                         for d in ("dist/sim", "dist/data") for p in (args.showdown / d).rglob("*.js"))
    prior = json.loads(args.verified_engine_report.read_text())
    if compiled != prior["compiled_oracles"]["showdown"]:
        raise ValueError("Compiled Showdown differs from the verified direct oracle")
    cases = expand(args.fixtures)
    seeds = [[42, n, 27, 91] for n in range(1, args.seeds + 1)]
    oracle_started = time.perf_counter()
    oracles = json.loads(subprocess.check_output(
        ["node", str(ROOT / "scripts/joint_turn_oracle.cjs"), str(args.showdown)],
        input=json.dumps({"fixtures": cases, "seeds": seeds}), text=True))
    oracle_seconds = time.perf_counter() - oracle_started
    rows, latencies = [], []
    for fixture, oracle in zip(cases, oracles, strict=True):
        if fixture["id"] != oracle["id"]:
            raise ValueError("Oracle fixture order changed")
        before = oracle["outcomes"][0]["before"]
        if any(o["before"] != before for o in oracle["outcomes"]):
            raise ValueError("Seed-dependent initial state requires another mapping contract")
        weather = {None: "", "Sun": "sunnyday", "Sand": "sandstorm"}[fixture["weather"]]
        if any(o["weather_before"] != weather for o in oracle["outcomes"]):
            raise ValueError("Initial weather mapping differs")
        state = mapped_state(fixture, before)
        if comparable(before) != native_projection(state):
            raise ValueError(f"Initial state projection mismatch: {fixture['id']}")
        state_string = state.to_string()
        start = time.perf_counter_ns()
        branches = generate_instructions(state, *engine_actions(fixture))
        latencies.append((time.perf_counter_ns() - start) / 1000)
        if not branches or any(not math.isfinite(b.percentage) or b.percentage < 0 for b in branches):
            raise ValueError("Invalid branch weights")
        if not math.isclose(sum(b.percentage for b in branches), 100, rel_tol=0, abs_tol=1e-4):
            raise ValueError("Branch weights do not total 100 percent")
        outcomes = []
        for branch in branches:
            after = state.apply_instructions(branch)
            if state.to_string() != state_string or after.reverse_instructions(branch).to_string() != state_string:
                raise ValueError("Engine instruction application is mutating or not reversible")
            outcomes.append({"probability": branch.percentage / 100,
                             "after": native_projection(after),
                             "instructions": [repr(i) for i in branch.instruction_list]})
        engine_full = {key(o["after"]) for o in outcomes}
        engine_nonhp = {key(comparable(o["after"], hp=False)) for o in outcomes}
        sampled_full = {key(comparable(o["after"])) for o in oracle["outcomes"]}
        sampled_nonhp = {key(comparable(o["after"], hp=False)) for o in oracle["outcomes"]}
        classification = ("sampled_projection_support_agrees" if sampled_full <= engine_full else
                          "hp_only_sampled_support_difference" if sampled_nonhp <= engine_nonhp else
                          "non_hp_sampled_support_difference")
        rows.append({"fixture": fixture, "initial_engine_state_sha256": hashlib.sha256(state_string.encode()).hexdigest(),
                     "initial_projection": before, "engine_outcomes": outcomes,
                     "showdown_outcomes": oracle["outcomes"], "classification": classification,
                     "showdown_unique_projections": len(sampled_full),
                     "engine_branch_probability_sum": sum(o["probability"] for o in outcomes),
                     "sampled_outcomes_outside_engine_support": len(sampled_full - engine_full)})
        print(f"{fixture['id']}: {len(branches)} branches, {classification}")
    report = {"schema_version": 1, "showdown_revision": PINS["showdown"], "engine_artifact": artifact,
              "compiled_showdown": compiled, "fixture_sha256": digest(args.fixtures),
              "expanded_fixtures_sha256": hashlib.sha256(key(cases).encode()).hexdigest(),
              "runner_sha256": digest(Path(__file__)), "mapping_helper_sha256": digest(ROOT / "scripts/check_damage_conformance.py"),
              "oracle_sha256": digest(ROOT / "scripts/joint_turn_oracle.cjs"), "seeds": seeds, "cases": rows,
              "engine_query_us": {"count": len(latencies), "median": statistics.median(latencies), "max": max(latencies)},
              "showdown_batch_seconds": oracle_seconds, "gate_passed": False,
              "limitations": ["controlled mechanic probes, not complete OU team coverage",
                              "seeded Showdown sample is not an exact distribution or probability comparison",
                              "projection omits counters, volatiles, field durations and request flags",
                              "known engine damage averaging may change HP supports",
                              "support labels are observations, not adjudications", "offline only; live agents unchanged"]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as out:
        json.dump(report, out, indent=2)
        out.write("\n")
    print(f"Saved {args.output}")


if __name__ == "__main__":
    main()
