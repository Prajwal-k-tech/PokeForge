# Frozen OU pool: mechanic coverage and multi-turn evidence

**Verified:** 2026-10-01. **Status:** offline diagnostic coverage; Gate 0B/1 remain open.

## Actual-team scan

All eleven hash-locked teams in `config/team_pools/gen9ou_control_v1.toml` were parsed and accepted
by the pinned local Gen 9 OU validator. Their 66 Pokémon contain **90 unique moves, 35 species,
27 abilities and 11 items**. The scan rotates each member into the lead against the next frozen
team's lead, submits every actual move slot and one voluntary switch per lead: **264 move-instance
jobs + 66 switch jobs = 330**. Sixteen fresh seeded Showdown battles per job yield **5,280 first-turn
observations**, not 5,280 different reachable scenarios, complete games or rankings.

The native `jointfix-v1` wheel is checked against the actual installed native/wrapper. Showdown
revision and compiled-file inventory match the verified oracle. Initial six-member/four-move
projections agree for all 330 jobs. Normalized native weights and non-mutating/reversible branch
applications pass in all jobs. PP is deliberately capped at eight (or lower move max PP); this
avoids upstream's intentional suppression of high-PP changes but is a **controlled state**, not
an ordinary ladder opening. Own/request-only canonical adapters are not involved: both sides'
fully specified states are authorized offline oracle inputs, never live hidden-state observations.

| Sampled projection label | Jobs |
|---|---:|
| Sampled final state lies in native projected support | 118 |
| Differences outside native support involve HP only | 184 |
| Differences remain in non-HP fields | 28 |
| Mapping/native runtime errors after harness correction | 0 |

These are **not simulator-accuracy percentages**. We do not test exact probability mass, all field/
volatile/duration/continuation state, team combinations or repeated-action history. HP-only labels
are not automatic approval of damage approximations. In 110 jobs, one selected action explicitly
needs additional state/continuation checks; 36 of these superficially match the present projection.
Thus even apparent projection matches cannot certify Future Sight, Wish, Encore, pivoting, etc.
Every move has at least one observed actor attempt in this sample; an attempt is not a successful
effect or proof of mechanic coverage. The saved summary contains move-by-move job IDs and caveats.

## Harness errors separated from engine defects

- The initial scan had nine projection errors because our status helper used `paralysis` while the
  actual engine enum is **`PARALYZE`**. The shared translation now uses `paralyze`; an actual native
  serialized-state round trip verifies it. Neither the engine source nor wheel changed.
- The final projection zeros fainted Pokémon's boost fields, just as Showdown does after fainting.
  Previously two assured-KO cases compared meaningless residual native side boosts with cleared
  Showdown boosts. This is explicit dead-member projection normalization, not an engine patch or
  justification to remove differences for living Pokémon.
- Mapping now preserves all six members and all supplied move PP, rather than the earlier pilot's
  fixed two-member/one-move slice. Old reports retain their own source hashes and measured scope;
  they are not relabeled as checks of the expanded helper.

## Non-HP findings and next correction targets

`summarize_frozen_pool.py` recomputes each non-HP support miss and saves an actual seed/log plus the
closest projected native branch. Those witnesses identify these families:

| Family | Jobs | Evidence / source diagnosis |
|---|---:|---|
| PP consumed before move-prevention checks | 20 | Fully paralyzed/frozen/confusion-prevented moves keep PP in Showdown. Engine decrements low PP before existing-status branching in `generate_instructions_from_move`. |
| Missing sampled critical-KO support | 3 | Hurricane critically faints Weezing-Galar in a saved seed before it acts; all native branches leave it alive and spend its PP. Averaged critical damage fails to preserve the KO boundary in this slice. |
| Non-Ghost Curse blocked by Good as Gold | 1 | Garganacl gains Atk/Def +1, Spe −1 in Showdown against Gholdengo; engine gains none. Its Curse choice defaults to opponent targeting despite a self boost, invoking the Good as Gold status-removal path. |
| Defog lacks Evasion decrease | 2 | Showdown lowers opposing Evasion by one; native boosts stay zero. `StatBoosts`/Defog choice represent no Evasion decrement in this path. |
| Fixed-damage contact lacks Static outcome | 1 | Blissey's Seismic Toss into Zapdos can trigger observed Static paralysis; native support lacks it. Its direct fixed-damage special-effect path bypasses ordinary damage-hit contact handling. |
| Poison Puppeteer confusion continuation | 1 | Malignant Chain poisons/confuses the target, whose confusion-prevented Stealth Rock leaves no hazard and spends no PP. Saved witness misses both hazard/PP fields. General cause still needs isolated controls; do not call this a separate proven missing-ability implementation. |

Pinned sources: engine locked 0.0.48 `src/genx/generate_instructions.rs`,
`choice_effects.rs:SEISMICTOSS`, `abilities.rs:GOODASGOLD`, and `src/choices.rs:CURSE/DEFOG`;
Showdown ordinary complete-turn logs are the independent outcome evidence. This scan identifies
correction targets, **does not implement them**, and does not fully adjudicate the 184 HP-only cases.

The first summary labeled 23 witnesses as PP-prevention because their nearest non-HP difference was
PP. Review of the saved full HP/log outcomes found three instead involve a missing critical faint.
The corrected summary checks absent KO support before assigning the PP family. Do not use closest
non-HP distance alone to infer causal bugs. This is concrete evidence that averaging stochastic
damage can alter whether a slower action happens, not merely shift final HP by a harmless amount.

The source-supported defects require separately labeled corrections and isolated regression
controls. Known upstream approximations may instead require conservative fallback/telemetry; this
project is not committed to rewriting every simulator mechanic before measuring an agent.

## Multi-turn oracle histories now saved

Four scripted scenarios use actual accepted frozen OU teams, normal PP and ordinary Showdown event
paths (no damage/PRNG/event overrides). Eight seeds each produce **32 trajectories / 96 decision
transitions**. Requests for both players and whitelisted delay/volatile scalar fields are retained.
Continuity is checked between every consecutive state; required mechanic effects are asserted:

1. Slowking-Galar sets Future Sight, switches to Zapdos, and the pending attack resolves on turn 3.
2. Alomomola uses Wish; switched-in Dondozo receives its heal after taking damage.
3. Chilly Reception creates snow and a mid-turn replacement request. Opponent waits; replacement
   completion advances to the next turn. Replacement is **not another full turn**.
4. Tinkaton's Encore changes Clefable's selected Moonblast to its previous Calm Mind, retaining
   the move lock/duration into the following request.

These are **Showdown-only oracle histories**. No Rust rollout or native-framework parser has yet
been compared against them. Internal timers are offline truth, not known player-visible counters;
the eventual canonical adapter must derive only what protocol evidence establishes and retain
uncertainty. Full spectator logs contain both players' private split lines, so they must be routed
through Showdown's player-channel extraction before reuse as public parser transcripts.

## Reproduction and artifacts

```bash
.venvs/engine-jointfix-v1/bin/python scripts/check_frozen_pool_turns.py \
  --seeds 16 --output .artifacts/conformance/frozen_pool/NEW_SCAN.json
python scripts/summarize_frozen_pool.py \
  --report .artifacts/conformance/frozen_pool/full_pool_v3_normalized.json \
  --output .artifacts/conformance/frozen_pool/NEW_SUMMARY.json
.venvs/engine-jointfix-v1/bin/python scripts/capture_frozen_multiturn.py \
  --seeds 8 --output .artifacts/conformance/frozen_pool/NEW_MULTITURN.json
PYTHONPATH=. python -m pytest -q tests
```

New report paths are required. `--oracle-report` reuses a prior scan's Showdown outcomes only after
checking manifest/compiled oracle/source hashes, seeds and scheduled jobs. The normalized V3 scan
reuses V1 outcomes for corrected projection, **not additional sampled coverage**.

| Artifact, relative to `.artifacts/conformance/frozen_pool/` | SHA256 |
|---|---|
| `full_pool_v1.json` (raw saved outcomes; obsolete projection error labels) | `0c76c8b8452caecfda7fea6dd407a5914221e727d21cd476f15726def40e5f0a` |
| `full_pool_v3_normalized.json` (authoritative corrected projection) | `2826d96254c7394e2e7681beef82525de811341bdcf8a805ec2d5cf803703289` |
| `coverage_and_witnesses_v2_adjudicated.json` | `e6bf07cb5cda07690db4800e5d3fe2be9be10ea57b3ff66a99cace0a3e0e7c73` |
| `multiturn_oracle_v2_verified.json` | `ac4a4041c53b69e1a140fa2495df106a0ba385956818e2032cfbd7b899550426` |

Showdown pin, wheel SHA and team source/license provenance remain as in the prior variant/pool
documents. Team dataset license is not declared: this remains a local research-only pool, not
authorization to redistribute exports in a public release. No PokéAgent-server legality, training,
public battles, submission or Elo claim follows from the local validator.

Fresh oracle batch: 15.551 seconds. Normalized native query median 70.893 µs, max 3,586.515 µs over
330 queries; shared-machine timing is not isolated p99 or live multi-world deadline evidence.
Three portable helper tests bring the project suite to **53 passed**; helper tests alone do not
prove the native mechanics. The actual scan and trajectory validations supply the scoped runtime
evidence above.

The V1 coverage summary has obsolete causal labels for three critical-KO witnesses; V1 multi-turn
capture predates explicit scenario/seed completeness checks. Neither is additional coverage.

Next: player-perspective trajectory routing, delayed/pivot/lock state reconstruction and continuation
tests, plus isolated controls for the diagnosed non-HP/KO defects. All live integration gates remain
open; original baseline and isolated engine binaries were not changed by this scan.

## Player-channel continuation increment

Normal Team Preview is enabled in the new capture mode. Two seeds per scenario produce eight
trajectories and sixteen player JSONL fixtures. The actual pinned Showdown channel extractor routes
updates; side updates go only to their owner, and the privileged `end` payload is never included.
Checks reject opponent requests, unsplit private lines and exact opponent HP. The JSONL room header
is synthetic; these are **offline player-stream fixtures, not WebSocket captures**.

Direct simulator requests have no `rqid`, whereas pinned FoulPlay requires it. The fixture models
the narrow pinned `server/room-battle.ts:receive` step: shared counter starts at 1, increments per
request, JSON parses/stringifies with the added ID. Raw simulator request strings are saved separately
in `simulator_requests`; every player request is checked against its original with only the ID removed.
This does not validate the complete room server, timer, network batching or live deadline behavior.
The full report still contains private oracle state and must not be sent to a policy.

The first direct-simulator fixture attempt exposed that missing-ID integration contract; it is not
a FoulPlay mechanics failure. The native adapters then correctly rejected Chilly Reception's
`-prepare` announcement under their former blanket charging-event guard. Pinned
`data/moves.ts:chillyreception` shows this is a same-turn `[premajor]` announcement rather than a
two-turn charge lock. The adapter now allows that exact event only; actual charging events still fail
closed. FoulPlay and Metamon agree on every Chilly Reception checkpoint for both seeds and both
perspectives: five per stream, **20 total**, including the actor's replacement and opponent's wait
at turn 1 before turn 2. Their original recorded-battle regression still agrees on all 25 checkpoints.

Future Sight and Wish transcripts are available but their counters remain unsupported in the canonical
adapter. Encore parser comparison was not performed in this increment. No Rust continuation, neural
encoder, hidden-set model, playing-strength or leaderboard claim follows from these checks.

```bash
.venvs/engine-jointfix-v1/bin/python scripts/capture_frozen_multiturn.py \
  --seeds 2 --output .artifacts/conformance/frozen_pool/NEW_PLAYER_REPORT.json \
  --player-output-directory .artifacts/golden_requests/NEW_PLAYER_FIXTURES
.venvs/foulplay-rebuild/bin/python scripts/check_framework_states.py \
  --framework foulplay --source .artifacts/sources/foul-play \
  --capture .artifacts/golden_requests/frozen_multiturn_players_v2_room/chilly_reception_midturn_switch-seed1-p1.jsonl \
  --output .artifacts/conformance/states/NEW_CHILLY_FOULPLAY.json
.venvs/metamon-rebuild/bin/python scripts/check_framework_states.py \
  --framework metamon --source .artifacts/sources/metamon \
  --capture .artifacts/golden_requests/frozen_multiturn_players_v2_room/chilly_reception_midturn_switch-seed1-p1.jsonl \
  --compare .artifacts/conformance/states/NEW_CHILLY_FOULPLAY.json \
  --output .artifacts/conformance/states/NEW_CHILLY_METAMON.json
```

Repeat the native commands for `seed2`, `p2` as appropriate. Fresh output paths are required.
Clean original source pins were recovered into the ignored `.artifacts/sources/` cache; baseline
dependencies, source revisions and checkpoints were not changed. Two helper regressions bring the
project suite to **55 passed**. Artifact hashes:

| Artifact relative to `.artifacts/conformance/` | SHA256 |
|---|---|
| `frozen_pool/multiturn_players_v2_room.json` | `abc9b628ac7e265853729860c98cd85e26a8f8a463f4cc4185cdeea40e603cfe` |
| `states/chilly_p1_seed1_foulplay_v4.json` | `d51bdda40d7be145e63d04fb354bd0f7b2b2af2c4918770d7ca33e9e1693a8a8` |
| `states/chilly_p1_seed1_metamon_v4.json` | `e249ff5d59ab6a099cf25d7e7ec1a41249c6a68c9f2e929ef6ffdd178b59901c` |
| `states/chilly_p1_seed2_foulplay_v4.json` | `58938159b652d5377040439ef882c7f13b05ee51d84ebeb676d8d7aca60d24ba` |
| `states/chilly_p1_seed2_metamon_v4.json` | `ef7c210005d1b40a0ca0cb99d46e8eb34f6078f6f88501680d8bd8e9dc4e8a28` |
| `states/chilly_p2_seed1_foulplay_v4.json` | `5b0d2a3342b4c7d887e609509f52035a396890b9da271cd1ae0d111f3fe337cc` |
| `states/chilly_p2_seed1_metamon_v4.json` | `0c034035966ad8983ad7428da504967b0eb9d6fa4dc8b16ac766ff8c527c5688` |
| `states/chilly_p2_seed2_foulplay_v4.json` | `bd9dd7669416f44a0536f3536f9eb50c23e305904832f1978662b7ffac8aa0ae` |
| `states/chilly_p2_seed2_metamon_v4.json` | `d6ae7b9df746c715925aced0ff3d19262226774aa2dc56cd4c636229fda02144` |
| `states/foulplay_v10_chilly_regression.json` | `8f13c3dd6f2e0f36288e9590db9d69e45a05f954b9a5c09e628973ea00b44af2` |
| `states/metamon_v10_chilly_regression.json` | `6157d2813968ec714dcaec9104192ab1faf6535a8b9bb80c711fb69bca25730f` |

The earlier `multiturn_players_v1.json` contains simulator requests without the modeled room envelope;
it is not the native comparison input. Existing reports retain their original harness hashes and scopes.
