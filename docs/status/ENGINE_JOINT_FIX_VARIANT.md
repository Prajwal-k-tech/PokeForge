# Isolated full-turn engine correction

**Verified:** 2026-10-01. **Variant:** `jointfix-v1`. **Status:** offline, not live-integrated.

## Measured outcome

- Recover at max HP 289 heals 145, then burn deals 18: final HP 227 agrees with Showdown.
- Contact into Rocky Helmet at attacker max HP 432 costs 72, not 71.
- Both speed-tie orders apply Helmet exactly once, instead of twice in one half of the order
  branches. Strictly faster/slower controls also retain one activation.

The paired audit verifies **four changed cases, fifteen unchanged**, with identical initial engine
states and seeded Showdown projections. Only the intended actor HP changes; other projected state
and branch weights remain unchanged. All five additional weather-recovery controls agree on the
checked final projection: 24 fixtures × 64 seeds = **1,536 complete Showdown turns**, not independent
games or an exact stochastic-distribution comparison.

The 50 direct-damage fixtures are rerun against both independent oracles. All 1,600 controlled roll
outputs still agree between Showdown and Smogon; all 50 engine regular/critical maxima are unchanged
from `critstats-v1`. The critical-stat fix is retained: **33 exact maximum pairs, 17 documented
arithmetic discrepancies**. Remaining arithmetic and collapsed roll supports are not fixed here.

## Correction and regression scope

The cumulative patch applies directly to the locked 0.0.48 archive, **instead of** the earlier
critical-stat patch. Three library files and one upstream test file change:

- `src/genx/damage_calc.rs`: unchanged critical-stat correction from `critstats-v1`.
- `src/genx/generate_instructions.rs`: pristine mutable move choices in each speed-order branch;
  ordinary Gen 5+ healing rounds half up, weather recovery uses Showdown fixed-point/half-ties-down
  behavior, and secondary/item healing retains truncation.
- `src/genx/items.rs`: Helmet uses `-1.0 / 6.0`, not `-0.166`.
- `tests/test_battle_mechanics.rs`: two weather-healing expectations at 100 max HP change from
  66 to 67 for this Gen 9 build, justified by the independent Showdown path.

Two library regressions check eight recovery tuples and single Helmet activation under three speed
relations, including non-mutating/reversible generation. The complete declared Gen 9/Tera Rust run
passes **229 library tests, 653 battle-mechanic tests, 28 other tests and one doctest**. Two legacy
expectations changed, so this is not an unchanged upstream test run or independent full simulator
conformance. Project Python tests: **50 passed**.

### The oracle rejected a proposed-fix error

The initial weather follow-up replaced `0.667` with exact mathematical two-thirds. The max-HP-653
Morning Sun fixture rejected it: Showdown heals **436**, not 435. Pinned
`data/moves.ts:morningsun/shoreup` uses `battle.modify`, which truncates the factor to a 4096-scale
integer and rounds half ties down (`sim/battle.ts:modify`). That differs from both rational 2/3
and ordinary Recover's `Math.round` path. The final patch preserves the upstream factor and
matches its fixed-point application; `choice_effects.rs` is unchanged.

| Weather recovery control | Max HP | Starting HP | Final actor HP, both backends |
|---|---:|---:|---:|
| Morning Sun in sun | 371 | 100 | 347 |
| Shore Up in sand | 371 | 100 | 347 |
| Morning Sun fixed-point boundary in sun | 653 | 100 | 536 |
| Morning Sun ordinary-weather half tie | 371 | 100 | 285 |
| Morning Sun sand/quarter-heal half tie | 370 | 100 | 192 |

These are Custom Game mechanic isolation probes, including artificial move/species/ability pairings,
not validated OU teams. Full weather duration/counter coverage is not claimed.

## Identity, licenses and reproducibility

Base archive SHA: `070010686f2aedff11e25137e696e301ccd80fd57c805d255464067fc905ca12`.
Cumulative patch SHA: `bd047b140d201592b676b44441599ae3d3a5061e6b7b502263546e4a5c024674`.
Wheel SHA: `524dbde4c452447cc87d8281f95372f180e1c9fc2e3d04a3c23c475ce7157a96`.

The wheel is retained under `.artifacts/conformance/engine/jointfix-v1/`, installed only in
`.venvs/engine-jointfix-v1`. Its base version still says 0.0.48; variant and hashes are mandatory.
Baseline and previous variant environments remain unchanged. Engine/oracles are MIT;
`patches/README.md` retains the upstream notice. Overall project/GPL distribution and dataset rights
are still separate gates.

The direct harness verifies installed native/wrapper versus wheel, the complete 46-file Rust library
inventory versus archive plus three locked replacements, the changed test-file hash, and reverse
patch applicability. The patch also applies to a fresh extraction. Build: Cargo.lock, maturin 1.12.6,
CPython 3.12.14, declared Gen 9/Tera features. These are observed hashes, not bit-identical compiler
reproducibility claims.

Showdown remains `a5df8274e85b0889bf2a9b3422a08b39732374fc`; calculator remains
`660b9b85f39ee59f4768f40a07676e7ad7d5ac0a`. Recovered calculator build uses locked TypeScript
4.9.5: `tsc -p . --ignoreDeprecations 5.0`. All 35 unbundled JS files match prior oracle hashes.
Two unused production bundles were not rebuilt, so the full inventories differ. The paired audit
permits only those two omissions. Installation reported nine dependency advisories; these are
isolated offline build dependencies, not a security clearance or live installation.

Commands after extracting the archive and applying the cumulative patch:

```bash
cargo test --offline --locked --no-default-features --features terastallization --quiet
maturin build --release --locked --offline --no-default-features \
  --features poke-engine/terastallization \
  --interpreter python

.venvs/engine-jointfix-v1/bin/python scripts/check_joint_turns.py \
  --engine-variant jointfix-v1 \
  --engine-wheel .artifacts/conformance/engine/jointfix-v1/poke_engine-0.0.48-cp312-cp312-manylinux_2_34_x86_64.whl \
  --seeds 64 --output .artifacts/conformance/joint_turns/jointfix_fresh_original.json
# Repeat with --fixtures tests/fixtures/joint_turn_recovery_v1.json and another new output.
```

The direct runner accepts `--engine-variant jointfix-v1`, that wheel, extracted `src/`, saved sdist,
recovered calculator, and existing critical-stat fixtures/adjudications. `audit_joint_engine_fix.py
--help` documents its five paired inputs and new output. Report paths must be new.

Authoritative report paths below are relative to `.artifacts/conformance/`:

| Report | SHA256 |
|---|---|
| `joint_turns/jointfix_v2_original_controls.json` | `454c32ec07d8889b72352f63e3142ee27e0e7b88a71966c1eda06917726d4ed9` |
| `joint_turns/jointfix_v2_weather_controls.json` | `1ec6c3dbbc7eb665891ba749b79fea42c571e39d2d8f4d67f21c5591d9da5917` |
| `damage/jointfix_v2_regression.json` | `e689bd89ef9618f242f1eed82a5635fdd24f21f91135cfb0da5e0c3f0db0ee67` |
| `joint_turns/jointfix_paired_audit_v2.json` | `16c02af2153f06fe1d79a6065a49d9b99a221fe2a7fee97a5e5e34e6308df35c` |

Repeat reports reproduce all 24 branch sets and 1,536 seeded states; timings/log timestamps differ.
Preliminary `jointfix_v1_*` and paired-audit-v1 reports are development diagnostics, **not** final
wheel evidence. The first weather run contains the rejected exact-two-thirds hypothesis.

Native query median/max: original controls 27.542/39.655 µs (19 calls); weather controls
26.640/40.997 µs (five calls). Showdown batches: 1.024/0.469 seconds including startup. Tiny offline
timings do not establish p99 multi-world search deadlines or speedup.

## Next boundary

Expand to frozen evaluation teams' mechanics and multi-turn history/state updates, with explicit
supported/approximate/unsupported behavior. Do not count repeats as new coverage. Measured arithmetic
differences may be acceptable planning approximations with conservative handling; neither a perfect
simulator nor high Elo is established. No live integration, training, public battle or PokéAgent
submission occurred in this slice.
