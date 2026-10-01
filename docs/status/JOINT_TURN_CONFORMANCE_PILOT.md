# First complete joint-turn comparison

**Verified:** 2026-10-01. **Status:** offline pilot; live search remains gated.

Follow-up: [`ENGINE_JOINT_FIX_VARIANT.md`](ENGINE_JOINT_FIX_VARIANT.md) records an isolated correction
for the diagnosed defects. The original pilot below remains evidence for the unchanged tested
`critstats-v1` runtime, not the later wheel.

## Measured result

Nineteen controlled Gen 9 Custom Game mechanic fixtures were each run through **64 seeded complete
Showdown turns** (1,216 fresh battles) and `poke-engine.generate_instructions`. There are no Showdown
damage-roll, critical-hit, randomizer or event overrides. Initial mapped projections agree in all
19 fixtures. Engine branch percentages normalize to 100 within float32 tolerance, applications
leave the input unchanged, and reversing every branch restores the initial engine state.

Thirteen fixtures' sampled final projections lie within the engine's projected support. Six have
HP-only support differences; none has a sampled difference outside the non-HP projected support.
**This is not 13/19 simulator accuracy, exact probability agreement, or competitive evidence.**
The seed sample is finite, and the projection intentionally checks only active slot, two supplied
members' HP/max HP, items, abilities, status, Tera, seven boosts, move PP, and four entry hazards.

Covered probes: setup/Leftovers, Protect priority, failed Sucker Punch into a status move, Good as
Gold blocking status, Spikes, Recover/burn, ordinary switching, Stealth Rock/Boots, Regenerator,
Air Balloon and Flying-Tera immunity, contact/Helmet with tied and unequal speed, Knock Off,
Life Orb, and an assured faint preventing the slower Pokémon's move. Some move/species pairings
are deliberately artificial isolation probes; **these are not validated OU teams**.

## Findings that change the next action

| Finding | Showdown | Tested engine | Diagnosis |
|---|---|---|---|
| Recover at 289 max HP, starting at 100, then burn | Heal 145, lose 18, finish 227 | Heal 144, lose 18, finish 226 | Gen 9 move recovery is rounded, not truncated. At even max HP 290, the control agrees. |
| One contact into Helmet, attacker max HP 432 | Lose 72, finish 360 | Lose 71, finish 361 | Engine uses `-0.166`, rather than exact one sixth with the appropriate integer treatment. Both strict-speed controls reproduce this. |
| Same contact, speed tie | One Helmet activation, attacker finishes 360 regardless of which moves first | Half the engine order mass gets two Helmet instructions, finishes 290; other half finishes 361 | Mutable move choices are reused between the two speed-order branches, accumulating item-added secondary effects. Strict-speed controls have one activation. |

Primary pinned source evidence, extracted from the locked 0.0.48 archive:
`src/genx/generate_instructions.rs:get_instructions_from_heal` truncates fractional recovery;
`src/genx/items.rs` adds Helmet as `Effect::Heal(-0.166)`;
`generate_instructions_from_move_pair`'s speed-tie arm passes the same mutable choices through both
`handle_both_moves` calls. Showdown `sim/battle-actions.ts` rounds move healing in Gen 5+;
`data/items.ts:rockyhelmet` calls damage with `source.maxhp / 6`.

These are **unfixed defects in the tested `critstats-v1` transition path**, not expected damage-roll
averaging. The critical-stat patch does not touch these files. Nevertheless this run directly
measures only the separately labeled variant; do not present it as a newly executed unchanged
baseline transition test.

The six discrepant fixture families are accounted for as follows:

- `recover_and_burn`: recovery rounding defect.
- `earthquake_and_residual`: collapsed damage-roll support plus the previously measured direct
  modifier-stage discrepancy (engine maxima 291/436 versus both direct oracles 290/434).
- `contact_helmet`: collapsed damage support, Helmet fraction, and duplicate speed-order effect.
- `contact_helmet_attacker_faster` / `contact_helmet_attacker_slower`: collapsed damage support and
  Helmet fraction; no duplicate activation in either control.
- `knock_off_balloon`: collapsed damage support plus the previously measured direct modifier-stage
  discrepancy (190/285 versus 188/282). Observed item removal agrees in the checked projection.

The coarse report labels describe sampled support only. They do not automatically adjudicate every
HP-only mismatch as harmless. In particular the Helmet and recovery findings would have been
missed by comparing only non-HP fields or by dismissing all HP differences as averaging.

## Runtime identity and reproducibility

Showdown source remains `a5df8274e85b0889bf2a9b3422a08b39732374fc`. Tracked changes are rejected
except the already documented package-lock edit. All compiled simulator/data JS file hashes equal
the saved direct-conformance oracle inventory. The actual engine native binary and Python wrapper
equal the earlier wheel-verified `critstats-v1` report, whose wheel SHA matches the artifact lock.
Some old `/tmp` sources/wheels no longer exist after session recovery. This check verifies the
**surviving installed runtime**, not a new source build or wheel reproducibility claim. The original
engine archive remains saved; its source was recovered into a new temporary directory for diagnosis.

```bash
.venvs/engine-critstats-v1/bin/python scripts/check_joint_turns.py \
  --seeds 64 \
  --output .artifacts/conformance/joint_turns/pilot_v3_verified.json
PYTHONPATH=. python -m pytest -q tests
```

The output path must be new; reports are not overwritten. V3 is the authoritative report:
SHA256 `f30a1c55806686d6589c2410057fe58506882a4472473911c14301ee235910c2`.
The prior V2 controls report SHA is
`2ab817698ea876563a8c0b291fc22b1e81001cfdfc29ccd120e683fdc9d85ae9`.
Their 19 native branch sets and all 1,216 seeded state outcomes agree on repeat. Timings, runner
hashes, and wall-clock `|t:|` protocol lines differ; full report bytes are not claimed identical.
V1 is an eight-seed diagnostic before the three additional controls, not independent coverage.

V3 measures 19 single native queries: median 35.065 µs, maximum 56.136 µs. The entire 1,216-battle
Showdown batch including process startup takes 1.114 seconds. These are tiny offline plumbing
measurements, **not** p99 search-deadline or realistic multi-world latency guarantees.
Two helper regression tests bring the project suite to **48 passed**. They test fixture expansion
and projection semantics, not simulator mechanics; the real runtime comparison supplies the latter
evidence within its declared slice.

## Remaining boundary

No full field/counter/volatile/request-flag mapping, exact stochastic probability comparison,
frozen-team coverage, multi-turn rollout conformance, hidden-set inference, or live adapter is
established here. PP is deliberately set to eight in every supplied move because this engine only
decrements low PP (`<10`); suppressing high-PP changes is an intentional upstream approximation,
not full PP conformance. No training, public battle or PokéAgent submission ran.

Next: make a **separately versioned** correction for speed-order choice isolation and the diagnosed
recovery/Helmet arithmetic; reproduce these controls and retain the direct-stat regression suite
before expanding to actual frozen-team mechanics and multi-turn transitions. The baseline remains
untouched. This pilot uses the existing native API and stdlib orchestration rather than adding a
second live damage calculator or speculative adapter layer.
