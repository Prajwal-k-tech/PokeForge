"""Serve pinned Minikazam for a fixed local Showdown challenge matchup."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import socket
import subprocess
import sys
import time
from importlib import metadata
from pathlib import Path
from types import MethodType


ROOT = Path(__file__).resolve().parents[1]
METAMON_REVISION = "0a00a759c9a4382a2877088d828302ec294a05a5"
CHECKPOINT_REVISION = "ac8e88e7da8dc2a2b85176d88f81fd8854b1445b"


def require_local_server() -> None:
    try:
        with socket.create_connection(("127.0.0.1", 8000), timeout=1):
            return
    except OSError as error:
        raise SystemExit("Local Showdown is not listening on port 8000") from error


def require_revision(source: Path) -> None:
    if (source / ".git").exists():
        actual = subprocess.check_output(
            ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
        ).strip()
    else:
        direct_url = json.loads(metadata.distribution("metamon").read_text("direct_url.json"))
        actual = direct_url.get("vcs_info", {}).get("commit_id")
    if actual != METAMON_REVISION:
        raise SystemExit(
            f"Metamon revision mismatch: expected {METAMON_REVISION}, found {actual}"
        )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_safe_metrics(values: dict[str, float]) -> dict[str, float | None]:
    metrics = {}
    for key, value in values.items():
        numeric = float(value)
        metrics[key] = numeric if math.isfinite(numeric) else None
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--team", type=Path, required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--opponent", required=True)
    parser.add_argument("--role", choices=["challenger", "acceptor"], required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--trajectories", type=Path)
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--model", default="Minikazam")
    parser.add_argument("--checkpoint", type=int)
    parser.add_argument("--protocol-debug", action="store_true")
    parser.add_argument("--strict-policy-gate", action="store_true",
                        help="Opt-in PokeForge local variant: mask after clipping and validate exact request identity.")
    parser.add_argument("--safety-log", type=Path,
                        help="New JSONL path required by --strict-policy-gate; never overwrites an old log.")
    args = parser.parse_args()
    if args.strict_policy_gate != (args.safety_log is not None):
        parser.error("--strict-policy-gate and --safety-log must be used together")

    cache = Path(os.environ.get("METAMON_CACHE_DIR", ROOT / ".artifacts/metamon"))
    os.environ["METAMON_CACHE_DIR"] = str(cache)
    require_local_server()

    import metamon
    import metamon.env.wrappers as wrappers
    from huggingface_hub import hf_hub_download
    from metamon.env import TeamSet
    from metamon.env.metamon_player import PokeAgentPlayer
    from metamon.rl.evaluate import pretrained_vs_challenge
    from metamon.rl.pretrained import get_pretrained_model

    if args.protocol_debug:
        logging.getLogger(args.username).setLevel(logging.INFO)

    require_revision(Path(metamon.__file__).resolve().parents[1])
    model = get_pretrained_model(args.model)
    checkpoint = args.checkpoint if args.checkpoint is not None else model.default_checkpoint
    checkpoint_file = (
        f"{model.model_name}/ckpts/policy_weights/policy_epoch_{checkpoint}.pt"
    )
    checkpoint_path = Path(hf_hub_download(
        repo_id="jakegrigsby/metamon",
        filename=checkpoint_file,
        revision=CHECKPOINT_REVISION,
        cache_dir=cache / "pretrained_models",
    ))

    wrappers.PokeAgentPlayer = PokeAgentPlayer
    attach_guard, safety_stats, safety_stream = None, None, None
    try:
        if args.strict_policy_gate:
            sys.path.insert(0, str(ROOT))
            from src.integration.metamon_guard import install_local_guard

            args.safety_log.parent.mkdir(parents=True, exist_ok=True)
            safety_stream = args.safety_log.open("x")
            attach_guard, safety_stats = install_local_guard(safety_stream)
        model.gin_overrides = (model.gin_overrides or {}) | {
            "MetamonAMAGOExperiment.traj_save_len": 10_000_000_000,
        }
        model.get_path_to_checkpoint = MethodType(
            lambda self, requested_checkpoint: str(checkpoint_path), model
        )

        inference_ms = []
        original_initialize = model.initialize_agent

        def initialize_with_timing(*init_args, **init_kwargs):
            experiment = original_initialize(*init_args, **init_kwargs)
            if attach_guard is not None:
                attach_guard(experiment.policy)
            original_get_actions = experiment.policy.get_actions

            def timed_get_actions(*policy_args, **policy_kwargs):
                started = time.perf_counter_ns()
                result = original_get_actions(*policy_args, **policy_kwargs)
                if experiment.DEVICE.type == "cuda":
                    import torch

                    torch.cuda.synchronize(experiment.DEVICE)
                elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
                inference_ms.append(elapsed_ms)
                print(f"POKEFORGE_INFERENCE_MS={elapsed_ms:.6f}", flush=True)
                return result

            experiment.policy.get_actions = timed_get_actions
            return experiment

        model.initialize_agent = initialize_with_timing
        team = TeamSet(str(args.team.resolve().parent), "gen9ou")
        team.team_files = [str(args.team.resolve())]
        results = pretrained_vs_challenge(
            pretrained_model=model,
            username=args.username,
            opponent_username=args.opponent,
            role=args.role,
            battle_format="gen9ou",
            team_set=team,
            total_battles=1,
            checkpoint=checkpoint,
            battle_backend="pokeagent",
            action_temperature=args.temperature,
            save_trajectories_to=str(args.trajectories) if args.trajectories else None,
            save_results_to=str(args.results),
            log_to_wandb=False,
        )
        def summarize(samples: list[float]) -> dict[str, float | int] | None:
            if not samples:
                return None
            ordered = sorted(samples)
            return {
                "count": len(ordered),
                "mean_ms": sum(ordered) / len(ordered),
                "p50_ms": ordered[len(ordered) // 2],
                "p95_ms": ordered[max(0, int(0.95 * len(ordered) + 0.999999) - 1)],
                "max_ms": ordered[-1],
            }

        timing = {
            "cold_start_ms": inference_ms[0] if inference_ms else None,
            "all": summarize(inference_ms),
            "warm": summarize(inference_ms[1:]),
        }
        print(
            "POKEFORGE_METAMON_METRICS="
            + json.dumps(
                {
                    "model": args.model,
                    "model_name": model.model_name,
                    "checkpoint": checkpoint,
                    "checkpoint_revision": CHECKPOINT_REVISION,
                    "checkpoint_sha256": sha256(checkpoint_path),
                    "evaluation": json_safe_metrics(results),
                    "inference": timing,
                    "policy_variant": "pokeforge-request-gated-v1" if args.strict_policy_gate else "upstream",
                    "safety": safety_stats,
                },
                sort_keys=True,
                allow_nan=False,
            ),
            flush=True,
        )
    finally:
        if safety_stream is not None:
            safety_stream.close()


if __name__ == "__main__":
    main()
