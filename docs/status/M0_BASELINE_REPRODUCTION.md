# M0 Baseline Reproduction Evidence

**Run date:** 2026-09-30<br>
**Format:** Gen 9 OU<br>
**Scope:** local pinned Pokémon Showdown only; these games do not measure competitive strength

## Shared fixture

Both systems used the same locally frozen team, SHA256
`ed74dca8676f5e148c33ab44fa3a7f10d4792662d5fc3b3d064610a5dfe9789a`. The pinned
Showdown validator accepted it as `gen9ou` before either run. The team export is not included because
its source and redistribution permission were not recorded. The hash identifies the input but is not
enough to reconstruct it.

The server was Pokémon Showdown
`a5df8274e85b0889bf2a9b3422a08b39732374fc`, launched locally with `--no-security`.
No public ladder or login service was used.

## FoulPlay

- Source: `6c467c081e862fb321adb405355beb41aba8e226`
- Engine: `poke-engine==0.0.48`, built with the Gen 9/Tera feature
- Runtime: `config/foulplay-runtime.lock.txt`
- Inference data: four exact hashes in `config/artifacts.lock.toml`
- Harness: `scripts/reproduce_foulplay_baseline.py`
- Opponent: poke-env `RandomPlayer`, using the same frozen team

Verified clean-environment rebuild run:

- battle ID `battle-gen9ou-173`;
- 10 turns;
- FoulPlay reported `Winner: PokeForgeFoulPlay`, `W: 1 L: 0`;
- the independent opponent reported `won=False lost=True turns=10`;
- saved replay SHA256
  `a4956c935cf4acb3b05032f4570f95ab8fa2a1402a554ae4b60592f862145656`.

The harness bypasses the public login endpoint only for a Showdown server explicitly launched with
`--no-security`. It does not alter search or battle decisions. The run used 25 ms per sampled search
world, one search worker, and one engine thread. FoulPlay sampled two hidden worlds per ordinary
standard-battle decision under this configuration.

## Metamon Minikazam

- Source: `0a00a759c9a4382a2877088d828302ec294a05a5`
- Checkpoint repository: `ac8e88e7da8dc2a2b85176d88f81fd8854b1445b`
- Checkpoint: Minikazam epoch 40, SHA256
  `dda9cf7752d68343992987319a96db0a4c87f011ae6fedbb0521e46f0385cc88`
- Runtime: `config/metamon-runtime.lock.txt`
- Backend: the checkpoint-declared `pokeagent` parser
- Harness: `scripts/reproduce_metamon_baseline.py`
- Opponent: Metamon `RandomBaseline`, using the same frozen team

Verified clean-environment rebuild run:

- battle ID `1930174369`;
- 25 turns in the saved result row;
- result `WIN`;
- average win rate `1.0` for the one-game smoke sample;
- valid-action fraction `1.0`;
- result CSV SHA256
  `39478b7ea0aaabc300783122635af0a1fe169b95f14f9ab39665122cd751c98f`.

The policy ran on the local RTX 3050. Two compatibility shims are explicit in the harness:

1. Metamon 1.6.0 defines `PokeAgentPlayer` but omits its import in `wrappers.py`.
2. AMAGO 3.4.0 supplies the float literal `1e10` to an integer `randint` bound; the harness uses the
   behaviorally identical integer `10_000_000_000`.

Neither shim changes the checkpoint, observation, action, reward, or policy logic.

The clean rebuild also found that Metamon's built wheel at the pinned commit omits required tokenizer
JSON files. The reproducible installation therefore installs `config/metamon-runtime.lock.txt`, then
installs the exact pinned source checkout with `--no-deps -e`. A normal wheel install is rejected as a
known-broken path rather than silently relying on files from another environment.

## Reproduction commands

Start the server:

```bash
node pokemon-showdown/pokemon-showdown start --skip-build --no-security
```

In another terminal:

```bash
.venv/bin/python scripts/reproduce_foulplay_baseline.py \
  --source /path/to/foul-play-at-6c467c081e862fb321adb405355beb41aba8e226

METAMON_CACHE_DIR="$PWD/.artifacts/metamon" \
  .venvs/metamon/bin/python scripts/reproduce_metamon_baseline.py
```

Generated logs and replays live under `.artifacts/baseline_runs/` and are intentionally ignored by
Git. Fresh environments `.venvs/foulplay-rebuild` and `.venvs/metamon-rebuild` were created from the
recorded locks and both commands were rerun successfully. The original baseline environments were not
used for those final games.
