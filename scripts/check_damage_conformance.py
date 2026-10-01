"""Offline direct-damage pilot against pinned Showdown, Smogon calc, and poke-engine."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import statistics
import subprocess
import tarfile
import time
import tomllib
import zipfile
from collections import Counter
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PINS = {"showdown": "a5df8274e85b0889bf2a9b3422a08b39732374fc",
        "calc": "660b9b85f39ee59f4768f40a07676e7ad7d5ac0a"}
STATS = ("hp", "atk", "def", "spa", "spd", "spe")
STATUS = {"brn": "burn", "par": "paralyze", "psn": "poison", "tox": "toxic",
          "slp": "sleep", "frz": "freeze", "": "none"}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_hash(paths):
    """Record the actual compiled/source files used, not just repository HEAD."""
    hashes = {name: digest(path) for name, path in sorted(paths)}
    return {"files": len(hashes), "sha256": hashlib.sha256(
        json.dumps(hashes, sort_keys=True).encode()).hexdigest(), "file_sha256": hashes}


def engine_artifact_lock(variant):
    lock = tomllib.loads((ROOT / "config/artifacts.lock.toml").read_text())
    name = {"baseline": "poke-engine-foulplay-built-wheel", "critstats-v1": "poke-engine-critstats-v1-built-wheel",
            "jointfix-v1": "poke-engine-jointfix-v1-built-wheel"}[variant]
    return next(a for a in lock["artifacts"] if a["name"] == name)


def verify_engine_wheel(path, variant="baseline"):
    import poke_engine
    import poke_engine.poke_engine as native

    expected = engine_artifact_lock(variant)["sha256"]
    if digest(path) != expected:
        raise ValueError("engine wheel differs from locked artifact")
    binary = Path(native.__file__)
    wrapper = Path(poke_engine.__file__)
    with zipfile.ZipFile(path) as wheel:
        names = [name for name in wheel.namelist() if name.endswith("/" + binary.name)]
        if len(names) != 1 or hashlib.sha256(wheel.read(names[0])).hexdigest() != digest(binary):
            raise ValueError("installed native engine differs from the locked wheel")
        if hashlib.sha256(wheel.read("poke_engine/__init__.py")).hexdigest() != digest(wrapper):
            raise ValueError("installed engine wrapper differs from the locked wheel")
    return {"variant": variant, "wheel_sha256": expected, "native_sha256": digest(binary),
            "wrapper_sha256": digest(wrapper), "license": "MIT"}


def verify_engine_source(archive_path, source, variant="baseline"):
    lock = tomllib.loads((ROOT / "config/artifacts.lock.toml").read_text())
    expected = next(a["sha256"] for a in lock["artifacts"]
                    if a["name"] == "poke-engine-foulplay-runtime")
    if digest(archive_path) != expected:
        raise ValueError("engine source archive differs from locked artifact")
    prefix = "poke_engine-0.0.48/src/"
    with tarfile.open(archive_path) as archive:
        archived = {m.name.removeprefix(prefix): hashlib.sha256(archive.extractfile(m).read()).hexdigest()
                    for m in archive.getmembers() if m.isfile() and m.name.startswith(prefix) and m.name.endswith(".rs")}
    actual = tree_hash((str(p.relative_to(source)), p) for p in source.rglob("*.rs"))
    patch_info = {}
    if variant != "baseline":
        variant_lock = engine_artifact_lock(variant)
        patch = ROOT / variant_lock["patch_source"]
        if digest(patch) != variant_lock["patch_sha256"]:
            raise ValueError("engine variant patch differs from lock")
        changes = variant_lock.get("changed_sources", {variant_lock.get("changed_source"): variant_lock.get("changed_source_sha256")})
        for changed, expected_hash in changes.items():
            if changed not in archived:
                raise ValueError("patch changes unknown source file")
            archived[changed] = expected_hash
        subprocess.run(["git", "apply", "--reverse", "--check", str(patch)], cwd=source.parent, check=True)
        patch_info = {"patch_sha256": digest(patch), "changed_sources": changes}
        if "changed_tests_sha256" in variant_lock:
            test_file = source.parent / "tests/test_battle_mechanics.rs"
            if digest(test_file) != variant_lock["changed_tests_sha256"]:
                raise ValueError("patched upstream test source differs from lock")
            patch_info["changed_tests_sha256"] = digest(test_file)
    if not archived or archived != actual["file_sha256"]:
        raise ValueError("audited Rust source differs from locked source archive")
    return actual | {"sdist_sha256": expected} | patch_info


def roll_summary(rolls, hp):
    """Conditional direct damage: explicitly no inferred hit/critical probabilities."""
    if len(rolls) != 16 or any(type(d) is not int or d < 0 for d in rolls) or hp <= 0:
        raise ValueError("requires sixteen nonnegative integer rolls and positive target HP")
    return {"support": [{"damage": damage, "probability": count / 16}
                        for damage, count in sorted(Counter(rolls).items())],
            "min": min(rolls), "max": max(rolls), "mean": sum(rolls) / 16,
            "p_ko_given_hit_and_critical_condition": sum(d >= hp for d in rolls) / 16}


def mixture_summary(worlds, hp):
    """Tiny offline belief fixture: coherent fully specified worlds, noncritical hits only."""
    if not worlds or any(not math.isfinite(w) or w < 0 for w, _ in worlds):
        raise ValueError("invalid world weights")
    if not math.isclose(sum(w for w, _ in worlds), 1.0, abs_tol=1e-12, rel_tol=0):
        raise ValueError("world weights must sum to one")
    support = Counter()
    for weight, rolls in worlds:
        for entry in roll_summary(rolls, hp)["support"]:
            support[entry["damage"]] += weight * entry["probability"]
    cumulative = 0.0
    q10 = None
    for damage, probability in sorted(support.items()):
        cumulative += probability
        if q10 is None and cumulative >= .1:
            q10 = damage
    return {"support": [{"damage": d, "probability": p} for d, p in sorted(support.items())],
            "mean": sum(d * p for d, p in support.items()), "p_zero": support[0],
            "q10": q10, "p_ko_given_hit_and_no_critical": sum(p for d, p in support.items() if d >= hp)}


def classify(case_id, engine_maxima, oracle_maxima, oracle_agreement, adjudications):
    if not oracle_agreement:
        return "oracle-ambiguity"
    if engine_maxima == oracle_maxima:
        return "direct-damage-match"
    known = adjudications.get(case_id)
    if known and known["engine_maxima"] == engine_maxima and known["oracle_maxima"] == oracle_maxima:
        return known["classification"]
    return "unclassified-mismatch"


def fixtures(path):
    source = json.loads(path.read_text())
    if "extends" in source:
        base = json.loads((path.parent / source["extends"]).read_text())
        source = base | {"pokemon": base["pokemon"] | source.get("pokemon", {}),
                         "cases": base["cases"] + source["cases"]}
    result = []
    for case in source["cases"]:
        fixture = {"id": case["id"], "move": case["move"], "weather": case.get("weather"),
                   "terrain": case.get("terrain"), "screens": case.get("screens", [])}
        for role in ("attacker", "defender"):
            poke = copy.deepcopy(source["defaults"] | source["pokemon"][case[role]] | case.get(role + "_override", {}))
            poke["evs"] = {stat: poke["evs"].get(stat, 0) for stat in STATS}
            poke["ivs"] = {stat: poke["ivs"].get(stat, 31) for stat in STATS}
            fixture[role] = poke
        result.append(fixture)
    return result


def adjudications(path):
    source = json.loads(path.read_text())
    inherited = adjudications(path.parent / source["extends"]) if "extends" in source else {}
    return inherited | source["cases"]


def engine_state(fixture, state):
    from poke_engine import Move, Pokemon, Side, SideConditions, State

    def side(role, move):
        poke = state[role]
        types = tuple(t.lower() for t in poke["types"])
        if len(types) == 1:
            types += ("typeless",)
        tera = poke["tera_type"]
        # poke-engine keeps the original types alongside the explicit Tera flag/type.
        stats = poke["stats"]
        pokemon = Pokemon(id=poke["species_id"], level=poke["level"], types=types, base_types=types,
                          hp=stats["hp"], maxhp=stats["hp"], attack=stats["atk"], defense=stats["def"],
                          special_attack=stats["spa"], special_defense=stats["spd"], speed=stats["spe"],
                          item=poke["item"] or "none", ability=poke["ability"], base_ability=poke["ability"],
                          nature=poke["nature"], evs=tuple(poke["evs"][stat] for stat in STATS),
                          weight_kg=poke["weight_kg"],
                          status=STATUS[poke["status"]],
                          terastallized=bool(tera), tera_type=tera.lower() if tera else "typeless",
                          moves=[Move(id="".join(c.lower() for c in move if c.isalnum()))])
        conditions = SideConditions(reflect=int(role == "defender" and "reflect" in fixture["screens"]),
                                    light_screen=int(role == "defender" and "lightscreen" in fixture["screens"]),
                                    aurora_veil=int(role == "defender" and "auroraveil" in fixture["screens"]))
        boosts = poke["boosts"]
        # Reject translation drift before attributing a discrepancy to damage code.
        assert pokemon.id == poke["species_id"] and pokemon.level == poke["level"]
        assert pokemon.types == types and pokemon.base_types == types
        assert pokemon.hp == pokemon.maxhp == stats["hp"]
        assert [pokemon.attack, pokemon.defense, pokemon.special_attack,
                pokemon.special_defense, pokemon.speed] == [stats[s] for s in STATS[1:]]
        assert pokemon.status == STATUS[poke["status"]]
        assert pokemon.item == (poke["item"] or "none") and pokemon.ability == poke["ability"]
        assert pokemon.nature == poke["nature"]
        assert math.isclose(pokemon.weight_kg, poke["weight_kg"], rel_tol=1e-6, abs_tol=1e-7)
        assert pokemon.evs == tuple(poke["evs"][s] for s in STATS)
        assert pokemon.terastallized == bool(tera) and pokemon.tera_type == (tera.lower() if tera else "typeless")
        mapped = Side(pokemon=[pokemon], side_conditions=conditions,
                    attack_boost=boosts.get("atk", 0), defense_boost=boosts.get("def", 0),
                    special_attack_boost=boosts.get("spa", 0), special_defense_boost=boosts.get("spd", 0),
                    speed_boost=boosts.get("spe", 0))
        assert [mapped.attack_boost, mapped.defense_boost, mapped.special_attack_boost,
                mapped.special_defense_boost, mapped.speed_boost] == [boosts.get(s, 0) for s in STATS[1:]]
        return mapped

    return State(side_one=side("attacker", fixture["move"]), side_two=side("defender", "Splash"),
                 weather=(fixture["weather"] or "none").lower(), weather_turns_remaining=-1,
                 terrain=fixture["terrain"].lower() + "terrain" if fixture["terrain"] else "none",
                 terrain_turns_remaining=-1)


def main():
    from poke_engine import calculate_damage

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--showdown", type=Path, default=ROOT / "pokemon-showdown")
    parser.add_argument("--calc", type=Path, required=True)
    parser.add_argument("--engine-wheel", type=Path, required=True)
    parser.add_argument("--engine-variant", choices=("baseline", "critstats-v1", "jointfix-v1"), default="baseline")
    parser.add_argument("--engine-sdist", type=Path, required=True)
    parser.add_argument("--engine-source", type=Path, required=True,
                        help="extracted source used to build the locked wheel")
    parser.add_argument("--fixtures", type=Path, default=ROOT / "tests/fixtures/damage_pilot_v1.json")
    parser.add_argument("--adjudications", type=Path, default=ROOT / "tests/fixtures/damage_pilot_adjudications_v1.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=50)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    if version("poke-engine") != "0.0.48":
        raise ValueError("this pilot requires the pinned poke-engine 0.0.48 runtime")
    engine_artifact = verify_engine_wheel(args.engine_wheel, args.engine_variant)
    engine_artifact["source"] = verify_engine_source(args.engine_sdist, args.engine_source, args.engine_variant)
    decisions = adjudications(args.adjudications)
    worktrees = {}
    compiled = {}
    for name, source in (("showdown", args.showdown), ("calc", args.calc)):
        revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
        if revision != PINS[name]:
            raise ValueError(f"wrong {name} revision: {revision}")
        worktrees[name] = subprocess.check_output(["git", "-C", str(source), "status", "--short"], text=True).splitlines()
        if worktrees[name] and not (name == "showdown" and worktrees[name] == [" M package-lock.json"]):
            raise ValueError(f"unreviewed source changes in {name}: {worktrees[name]}")
        dirs = [source / "dist/sim", source / "dist/data"] if name == "showdown" else [source / "calc/dist"]
        compiled[name] = tree_hash((str(p.relative_to(source)), p) for directory in dirs for p in directory.rglob("*.js"))
    cases = fixtures(args.fixtures)
    oracle_output = subprocess.check_output(["node", str(ROOT / "scripts/damage_oracles.cjs"),
                                           str(args.showdown), str(args.calc)],
                                          input=json.dumps(cases), text=True)
    oracles = json.loads(oracle_output)
    rows, latencies = [], []
    for fixture, oracle in zip(cases, oracles, strict=True):
        if fixture["id"] != oracle["id"]:
            raise ValueError("oracle case order changed")
        for role in ("attacker", "defender"):
            if oracle["state"][role]["stats"] != oracle["calc_stats"][role]:
                raise ValueError(f"state/stat mapping differs in {fixture['id']} {role}")
        start = time.perf_counter_ns()
        state = engine_state(fixture, oracle["state"])
        mapping_us = (time.perf_counter_ns() - start) / 1000
        move = "".join(c.lower() for c in fixture["move"] if c.isalnum())
        maxima, _ = calculate_damage(state, move, "splash", True)
        for _ in range(args.repeats):
            start = time.perf_counter_ns()
            calculate_damage(state, move, "splash", True)
            latencies.append((time.perf_counter_ns() - start) / 1000)
        expected_maxima = [max(oracle["showdown"][kind]) for kind in ("regular", "critical")]
        exact_oracles = oracle["showdown"] == oracle["smogon_calc"]
        maximum_agreement = maxima == expected_maxima
        summaries = {kind: roll_summary(oracle["showdown"][kind], oracle["state"]["defender"]["stats"]["hp"])
                     for kind in ("regular", "critical")}
        row = {"fixture": fixture, "oracle": oracle, "engine_maxima": maxima,
               "engine_state_sha256": hashlib.sha256(state.to_string().encode()).hexdigest(),
               "mapping_us": mapping_us, "oracle_roll_agreement": exact_oracles,
               "engine_maximum_agreement": maximum_agreement,
               "classification": classify(fixture["id"], maxima, expected_maxima, exact_oracles, decisions),
               "adjudication": decisions.get(fixture["id"]),
               "oracle_conditional_damage": summaries,
               "engine_damage_support": None, "engine_damage_mean": None,
               "p_hit": None, "p_crit": None, "p_ko_on_hit": None,
               "p_ko_before_residual": None, "p_ko_end_of_turn": None,
               "limitations": ["no full engine rolls", "no accuracy/joint-transition/residual outcome", "not live-integrated"]}
        rows.append(row)
        print(f"{fixture['id']}: oracles={'agree' if exact_oracles else 'DIFFER'} engine={maxima} expected={expected_maxima}")
    ordered = sorted(latencies)
    by_id = {r["fixture"]["id"]: r for r in rows}
    mixtures = {}
    for action, ids in (("earthquake", ["physical_super_effective", "air_balloon_ground_immunity"]),
                        ("knockoff", ["knock_off_leftovers_control", "knock_off_air_balloon"])):
        selected = [by_id[i] for i in ids]
        mixtures[action] = mixture_summary([(0.5, r["oracle"]["showdown"]["regular"]) for r in selected],
                                            selected[0]["oracle"]["state"]["defender"]["stats"]["hp"])
    report = {"schema_version": 2, "pins": PINS | {"poke_engine": "0.0.48"}, "worktrees": worktrees,
              "fixture_sha256": digest(args.fixtures), "runner_sha256": digest(Path(__file__)),
              "expanded_fixtures_sha256": hashlib.sha256(json.dumps(cases, sort_keys=True).encode()).hexdigest(),
              "node_oracle_sha256": digest(ROOT / "scripts/damage_oracles.cjs"), "cases": rows,
              "adjudications_sha256": digest(args.adjudications),
              "expanded_adjudications_sha256": hashlib.sha256(json.dumps(decisions, sort_keys=True).encode()).hexdigest(),
              "engine_artifact": engine_artifact, "compiled_oracles": compiled,
              "classification_counts": dict(Counter(row["classification"] for row in rows)),
              "toy_belief_mixture": {"scope": "illustration only: 50/50 Leftovers/Air Balloon, conditional noncritical hits; not learned priors or a policy",
                                     "results": mixtures},
              "engine_query_us": {"count": len(ordered), "mean": statistics.fmean(ordered),
                                  "p50": statistics.median(ordered), "p95": ordered[math.ceil(.95 * len(ordered)) - 1],
                                  "p99": ordered[math.ceil(.99 * len(ordered)) - 1], "max": ordered[-1]},
              "gate_passed": False, "scope": "controlled direct-hit pilot; not full transition/Gen 9 OU conformance"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        stream.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(args.output)


if __name__ == "__main__":
    main()
