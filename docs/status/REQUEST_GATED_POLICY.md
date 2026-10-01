# Request-gated neural policy: local validation

**Date:** 2026-09-30<br>
**Status:** opt-in local harness variant, not the complete PokeForge architecture

## What changed

`src/integration/policy_gate.py` derives the 13-index legality map from the exact current Showdown
request and immutable own Team Preview identities. It removes illegal probability mass **after**
upstream clipping, preserving relative probabilities among legal indices. Empty legal mass,
changed identities, unsupported revival/Recharge, and stale exact request hashes fail closed.

`src/integration/metamon_guard.py` installs only inside the optional isolated evaluation process:

1. Capture the exact request substring before upstream JSON parsing.
2. Tag the corresponding observation with its SHA256 bytes through the environment queue.
3. Check that tag before inference, then remove it before the unchanged encoder sees the observation.
4. Reapply the exact-request mask to the actor's **post-clipping** categorical probabilities.
5. Before transmission, recheck the request hash and construct a legal, request-bound wire choice
   with `rqid`. Switch commands use the current request position resolved from stable slots.
6. Log requests, activations, raw/restricted probabilities, emitted choices, server errors, and
   attempted default-choice fallbacks. An unvalidated upstream default fallback is disabled.

The upstream source and checkpoint weights remain unchanged. The backend remains `pokeagent`,
not a migration to the newer replay parser. This is an inference-policy change and is labeled
`pokeforge-request-gated-v1`; it must not be presented as exact upstream reproduction.

The installer is deliberately limited to **one synchronous local Gen 9 OU policy stream**. It
patches in-memory wrapper methods in that child process; it is not a general parallel-serving API.
Unknown mechanics and full semantic state agreement are still outside this validation. No public
Showdown or PokéAgent battles were launched.

## Verified run

The first implementation completed a side-swapped local pair with 172 choices and no rejected
commands. It lacked the later observation-hash tag and complete bypass counters, so it remains a
separate preliminary diagnostic, not the authoritative validation below.

The strengthened implementation completed the same team pairing in two fresh local games:

```bash
.venv/bin/python scripts/benchmark_baselines.py \
  --foulplay-source /tmp/pokeforge-audit.SrV7C4/foul-play \
  --pairs 1 --start-pair 3 --search-time-ms 100 --metamon-checkpoint 40 \
  --metamon-strict-policy-gate \
  --output .artifacts/baseline_runs/head_to_head/request_gated_pair4_v2_20260930 \
  --timeout 240
```

Use a fresh output directory when reproducing. The harness refuses an existing directory; safety
logs also refuse overwrite. The result artifact is `summary.json`, SHA256
`1db02f551914c9106c333276317e344b791b379c45381d3b3e2a673215416808`.

| Game | Neural decisions | Forced replacements | Warm mean / p95 / max | Neural valid fraction |
|---:|---:|---:|---|---:|
| 7 | 59 | 7 | 2.57 / 3.43 / 3.96 ms | 1.0 |
| 8 | 76 | 6 | 2.76 / 3.91 / 4.36 ms | 1.0 |

Both games: zero recorded gate-rejected commands, zero observed server errors, zero attempted
unvalidated default fallbacks. All **135** choices and **13** forced replacements have matching
masked distributions and exact request hashes in the saved traces. Masked-out probabilities are
exactly zero, and legal probability ratios are preserved. The largest removed illegal mass in one
decision was `0.0119760493` (about 1.20%). This measures probability removal, not an observed
counterfactual illegal sample: the variant never samples the unprotected distribution.

FoulPlay won both games. The earlier preliminary pair split 1–1. These tiny stochastic samples
cannot establish strength, non-inferiority, or a speedup over the raw baseline. Warm timings are
in-process inference measurements, not full end-to-end choice latency. Cold starts here were
1.46 and 1.66 seconds and still need prewarming before rated deployment.

## Trace audit and provenance

```bash
python scripts/check_policy_trace.py \
  --log .artifacts/baseline_runs/head_to_head/request_gated_pair4_v2_20260930/game_007/safety.jsonl \
  --log .artifacts/baseline_runs/head_to_head/request_gated_pair4_v2_20260930/game_008/safety.jsonl \
  --output .artifacts/conformance/actions/request_gated_v2_trace_audit.json
```

The audit was reproduced to a second output file with an identical SHA256:
`38488b2b71f35ee2e49f7b0a82367f96d72200ea4d3130c6885da779a3769161`.
It recomputes received hashes, slot/index legality, restricted distributions, and emitted wire
choices; it rejects missing distribution/choice pairs, incorrect wire choices, and failure events.
Its scope is recorded action/probability/request consistency, **not independent full simulator
conformance**. The separate pinned formatter differential remains the independent action-boundary
check for its covered fixtures.

Source hashes at validation:

- `src/integration/policy_gate.py`:
  `2aec6a97f824aa1f2aa26bfff84d3411f514f8a1a82cae07c863f8f0d028f906`.
- `src/integration/metamon_guard.py`:
  `1b66094f67e70cbeeb8081a0230a846b7878297a72a6b00706c3d16f5aa111a2`.

The model is pinned Minikazam epoch 40 (checkpoint SHA256
`dda9cf7752d68343992987319a96db0a4c87f011ae6fedbb0521e46f0385cc88`) with the source/environment
pins from M0. The larger full-state, special-mechanics, damage/transition, license, and competitive
evaluation gates remain open. This completes a bounded policy-sampling safety slice; it does not
complete the Safety Shield, hybrid, opponent adaptation, or leaderboard submission.
