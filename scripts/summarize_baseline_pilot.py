"""Audit explicitly selected completed games without launching or modifying either baseline."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
import tomllib
from pathlib import Path

from benchmark_baselines import ROOT, parse_tagged_json, sha256


def timing(samples):
    ordered = sorted(samples)
    return {
        "count": len(ordered), "mean_ms": statistics.fmean(ordered),
        "p50_ms": statistics.median(ordered),
        "p95_ms": ordered[math.ceil(0.95 * len(ordered)) - 1],
        "p99_ms": ordered[math.ceil(0.99 * len(ordered)) - 1],
        "max_ms": ordered[-1],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "config/evaluations/m1_pilot_v1.toml")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = tomllib.loads(args.manifest.read_text())
    games, foul_samples, meta_samples, cold_starts = [], [], [], []
    for segment in manifest["segments"]:
        directory = ROOT / segment["directory"]
        if "summary_sha256" in segment and sha256(directory / "summary.json") != segment["summary_sha256"]:
            raise ValueError("continuation summary hash mismatch")
        for index in segment["games"]:
            folder = directory / f"game_{index:03d}"
            foul_path, meta_path = folder / "foulplay.log", folder / "metamon.log"
            foul_text, meta_text = foul_path.read_text(), meta_path.read_text()
            csv_paths = list((folder / "metamon_results").glob("*.csv"))
            if len(csv_paths) != 1:
                raise ValueError(f"expected one CSV: {folder}")
            with csv_paths[0].open(newline="") as stream:
                rows = [{key.strip(): value.strip() for key, value in row.items()} for row in csv.DictReader(stream)]
            if len(rows) != 1 or rows[0]["Result"] not in {"WIN", "LOSS"}:
                raise ValueError(f"ambiguous result: {folder}")
            row = rows[0]
            winner = row["Player Username"] if row["Result"] == "WIN" else row["Opponent Username"]
            observed = re.findall(r"Winner: (\S+)", foul_text)
            tags = set(re.findall(r"Initialized (battle-gen9ou-\d+)", foul_text))
            if len(observed) != 1 or observed[0].lower() != winner.lower() or len(tags) != 1:
                raise ValueError(f"inconsistent or ambiguous battle identity/outcome: {folder}")
            meta_metrics = parse_tagged_json(meta_text, "POKEFORGE_METAMON_METRICS")
            foul_metrics = parse_tagged_json(foul_text, "POKEFORGE_FOULPLAY_METRICS")
            fp = [float(value) for value in re.findall(r"POKEFORGE_DECISION_MS=([\d.]+)", foul_text)]
            mp = [float(value) for value in re.findall(r"POKEFORGE_INFERENCE_MS=([\d.]+)", meta_text)]
            if len(fp) != foul_metrics["count"] or len(mp) != meta_metrics["inference"]["all"]["count"]:
                raise ValueError(f"timing counts differ: {folder}")
            valid = next(value for key, value in meta_metrics["evaluation"].items() if "Valid Actions" in key)
            steps = int(row["Turn Count"])
            invalid_count = round((1 - valid) * steps)
            if len(mp) != steps or not math.isclose(valid, 1 - invalid_count / steps, abs_tol=1e-8):
                raise ValueError(f"cannot recover valid-action counts: {folder}")
            games.append({"game_index": index, "directory": str(folder.relative_to(ROOT)),
                          "battle_tag": next(iter(tags)), "metamon_won": row["Result"] == "WIN",
                          "metamon_decision_steps": steps, "metamon_invalid_selections": invalid_count,
                          "last_showdown_turn_logged": max(map(int, re.findall(r"Turn: (\d+)", foul_text))),
                          "log_sha256": {"foulplay": sha256(foul_path), "metamon": sha256(meta_path)},
                          "result_csv_sha256": sha256(csv_paths[0])})
            foul_samples.extend(fp)
            meta_samples.extend(mp[1:])
            cold_starts.append(mp[0])
    if len({game["game_index"] for game in games}) != len(games) or len({game["battle_tag"] for game in games}) != len(games):
        raise ValueError("selected games must have distinct indices and battle tags")
    report = {"schema_version": 1, "manifest_sha256": sha256(args.manifest), "manifest": manifest,
              "games": games, "metamon_wins": sum(game["metamon_won"] for game in games),
              "foulplay_wins": sum(not game["metamon_won"] for game in games),
              "metamon_invalid_selections": sum(game["metamon_invalid_selections"] for game in games),
              "foulplay_decision_timing": timing(foul_samples), "metamon_warm_timing": timing(meta_samples),
              "metamon_cold_start_range_ms": [min(cold_starts), max(cold_starts)]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        stream.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key not in {"games", "manifest"}}, indent=2))


if __name__ == "__main__":
    main()
