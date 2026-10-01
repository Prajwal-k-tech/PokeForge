# M1 Baseline Benchmark Evidence

**Status:** in progress<br>
**Run date:** 2026-09-30<br>
**Format:** local pinned Gen 9 OU<br>
**Purpose:** validate the paired benchmark and measure runtime; small samples are not strength claims

## Frozen control pool

`config/team_pools/gen9ou_control_v1.toml` freezes 11 teams from Metamon's v5
`competitive/gen9ou` archive. Each exact export passes Pokémon Showdown
`a5df8274e85b0889bf2a9b3422a08b39732374fc`. Five other archived teams were excluded because the
pinned current validator rejects Tera Blast.

The original files and hashes remain unchanged. The FoulPlay boundary strips trailing whitespace in
a temporary copy because its export parser otherwise turns the archive's terminal blank block into a
seventh Pokémon. This is an input-normalization compatibility fix, not a team edit.

## Paired harness smoke

`scripts/benchmark_baselines.py` performs the following before reporting a result:

- verifies all manifest hashes and validates every team with pinned Showdown;
- launches pinned FoulPlay and Metamon in their isolated environments;
- swaps both teams and challenger/acceptor roles within each pair;
- saves both stdout logs, Metamon result CSV, and compressed trajectory;
- records model/search timings, legal-action fraction, battle IDs, revisions, and artifact hashes;
- fails on process error, missing metric tags, missing result rows, or timeout.

The clean two-game smoke artifact is
`.artifacts/baseline_runs/head_to_head/paired_smoke_20260930_c/summary.json`, SHA256
`0c9943451d7772506d241d9f43f7d371c12ca334e7bc8fc755a9e6a4e648c8ee`.

| Game | FoulPlay team / role | Minikazam team / role | Winner | Metamon decision steps |
|---:|---|---|---|---:|
| 1 | team 5 / challenger | team 6 / acceptor | FoulPlay | 31 |
| 2 | team 6 / acceptor | team 5 / challenger | FoulPlay | 30 |

Both Metamon legal-action fractions were 1.0. Warm Minikazam mean inference was 4.82–5.12 ms and
warm p95 was 5.26–6.32 ms. Its one-time compilation was 3.69–3.71 s. FoulPlay used 25 ms per hidden
world for this harness smoke; mean decisions were 96.00–102.83 ms and p95 was 116.81–117.91 ms.

Earlier manual orientation checks produced two Minikazam wins. Together these contradictory tiny
samples demonstrate why neither run is a ranking.

## Cross-team pilot: six complete side-swapped games

The first uninterrupted portion of the 100 ms/world pilot completed three full pairs (six games)
before the local server/process session was interrupted while beginning game 8. The six completed
games are retained at
`.artifacts/baseline_runs/head_to_head/m1_pilot_5pairs_100ms_20260930_b/`; game 7 is retained as
an unpaired diagnostic artifact and is deliberately excluded from every aggregate below.

| Pair | Teams (swapped across games) | Minikazam wins | FoulPlay wins | Metamon decision steps (game 1 / game 2) |
|---:|---|---:|---:|---|
| 1 | team 5 vs team 6 | 0 | 2 | 57 / 50 |
| 2 | team 7 vs team 8 | 0 | 2 | 48 / 29 |
| 3 | team 9 vs team 10 | 1 | 1 | 59 / 117 |

All six runs completed legally with Minikazam's recorded valid-action fraction equal to **1.0**.
FoulPlay won 5/6. This is **not** a strength conclusion: six games, three team pairings, and one
model checkpoint cannot establish an Elo difference or control for matchup variance.

The runtime evidence is nevertheless useful. Across all 349 recorded FoulPlay decisions, the mean
was 211.48 ms, p50 255.13 ms, p95 271.63 ms, p99 283.52 ms, and maximum 801.75 ms. Across the 354
*warm* Minikazam inferences (cold compile excluded), the mean was 4.73 ms, p50 4.57 ms, p95 5.98 ms,
p99 6.40 ms, and maximum 9.35 ms. Minikazam cold starts ranged from 3.74 to 4.25 seconds in these
six processes, so production ladder operation must warm the policy before challenging.

The result has two concrete engineering consequences: FoulPlay's 100 ms/world configuration is
comfortably inside an 8-second decision cap in this pilot, and a neural prior can be evaluated many
times inside a search budget. It does **not** show that adding the prior improves decisions.

The harness now writes `progress.json` after every completed game. This prevents a long run being
misrepresented as absent evidence merely because a later game or its parent process stops.

## Recovered completion: five pairs, ten selected games

Reinspection found a **completed** continuation at
`.artifacts/baseline_runs/head_to_head/m1_pilot_pairs4_5_100ms_20260930/summary.json`, SHA256
`3f088795f2a633efdd0021c3f38cc9bb2d29cf4e90aaff2e5cb8c45d33c56403`. Its four games complete
the originally planned final two pairs. The selected ten games therefore comprise games 1–6 above
and games 7–10 from this continuation, not the interrupted run's unmatched game 7.

| Pair | Teams | Minikazam wins | FoulPlay wins | Metamon decision steps |
|---:|---|---:|---:|---|
| 4 | team 11 / team 12 | 0 | 2 | 60 / 69 |
| 5 | team 13 / team 14 | 0 | 2 | 44 / 48 |

Overall: **FoulPlay 9 wins, Minikazam epoch 40 one win**. This is an exploratory pilot, not an Elo
estimate or leaderboard comparison. The continuation overlapped an accidental duplicate pair-4 run
on the same host/server, with reused agent usernames. Distinct battle tags and mirrored log/CSV
outcomes were checked, but resource isolation and controlled seeds were not established. The
duplicate pair is retained separately and excluded, regardless of its outcome. Do not pool its
latency as if it were an isolated experiment.

`config/evaluations/m1_pilot_v1.toml` fixes segment selection and exclusions.
`scripts/summarize_baseline_pilot.py` verifies each selected winner against the other agent's CSV,
unique battle tags/indices, timing sample counts, and validity counts before reporting. Reproduce to
a **new** output path (it refuses overwrite):

```bash
python scripts/summarize_baseline_pilot.py \
  --output .artifacts/baseline_runs/head_to_head/m1_pilot_recovered_v1.json
```

Report SHA256 `06a3ba044988a8ce025d8a3c0e15f980da62623b5394ef7d7bd69b9925509526`.
Across 557 FoulPlay decisions: mean 215.51 ms, p50 255.89 ms, p95 274.97 ms, p99 287.63 ms,
maximum 801.75 ms. Across 571 warm Minikazam inferences: mean 4.85 ms, p50 4.66 ms, p95 6.32 ms,
p99 8.49 ms, maximum 16.07 ms. Cold starts span 3.74–4.25 seconds. These timings exclude full
end-to-end protocol overhead and carry the shared-load limitation above.

**Metric correction:** upstream CSV `Turn Count` is `PokeEnvWrapper.turn_counter`, incremented on
each `step`; pivot/replacement choices can add steps within one Showdown turn. Tables here report
decision steps, not actual battle turns. For example, continuation game 8 records 69 steps but the
last FoulPlay Showdown turn logged is 59. New audit reports retain both labels separately.

### One invalid upstream selection and a sampling defect

Continuation game 8 has valid-action fraction `68/69 = 0.9855072463768116`; the other selected nine
games record 1.0. At trajectory index 43 (zero-based), Walking Wake needs forced replacement after
Flip Turn but the selected index is `1`, a move index. Three replacement candidates are recorded.
Upstream `PokeEnvWrapper.action_to_move` sends this `None` order to `on_invalid_order`, which chooses
a random legal action. This is an **invalid policy selection with legal fallback**, not proof of an
illegal command reaching Showdown. A completed game does not imply zero fallbacks.

An independent probe of the pinned `MetamonDiscrete` exposes a concrete sampling hazard: its
`clip_prob_low=0.001` floor restores mass on indices previously masked to negative-infinity logits.
With three legal switches, illegal choices get total probability `0.0099009918`. This does **not**
by itself prove the recorded game's cause: that run did not log per-decision masks/logits and request
IDs. The probe is saved in `.artifacts/conformance/actions/metamon_v3_sampling.json`. Keep the exact
upstream baseline unchanged; a future protected variant must mask after clipping and before sampling,
validate against the current exact request hash, and separately report raw invalid intent/fallbacks.

## Second checkpoint and Abra audit

Minikazam epoch 46 is the second exact public Gen 9 checkpoint reproduced on this machine:

- repository revision `ac8e88e7da8dc2a2b85176d88f81fd8854b1445b`;
- SHA256 `a7bccf96b8159438e92b95b2f518488ba3519b27575e640ae3508587bb71031e`;
- strict match of 134 keys and 4,761,813 checkpoint tensor elements;
- one completed game with 56 Metamon decision steps against FoulPlay at its upstream-default 100 ms/world setting;
- Metamon valid-action fraction 1.0 and no deadline loss;
- warm inference mean 4.815 ms, p95 6.017 ms, maximum 6.721 ms;
- one-time CUDA compilation 5,741.658 ms.

The saved result CSV is
`.artifacts/baseline_runs/minikazam46_vs_foulplay_smoke/metamon_results/battle_log_PokeForgeMini46_gen9ou.csv`,
SHA256 `3ebe494a0937a441280cf1e23d3b6bb6cfab9e2efede0f0a089b91b1ea6f8d4b`.
FoulPlay won this single game; that result is plumbing evidence only.

Abra epoch 40 was also downloaded and hash-verified (SHA256
`8f473d8b5cfb344925b753e0477b327c81012c01d000aa98e31096e25479b895`), but its declared
configuration requires FlashAttention 2. The pinned environment does not contain `flash-attn`, and
the host has no CUDA compiler for a source build. Initialization therefore failed before battle with
the explicit AMAGO assertion `Missing flash attention 2 install`. Replacing it with Vanilla or Flex
attention would be a backend migration experiment, not an exact reproduction, so Abra is recorded as
blocked rather than silently altered.

## Current interpretation

- The paired harness is operational and side/team symmetric.
- Two exact, hardware-compatible Gen 9 checkpoints from the public Minikazam run are operational.
- Warm neural inference is negligible relative to the Standard Timer; cold compilation must happen
  before entering the ladder.
- FoulPlay at 100 ms/world remains comfortably below the eight-second choice cap in the observed
  selected games, but isolated full-pool p99 and end-to-end latency are still required.
- Raw Minikazam is not a zero-fallback baseline. Action mapping passes do not establish sampling safety.
- No head-to-head ordering is established yet.
