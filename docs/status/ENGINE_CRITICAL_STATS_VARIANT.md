# Isolated critical-stat engine correction

**Verified:** 2026-09-30. **Status:** offline experiment, not live-integrated.
**Variant:** `critstats-v1`, based on the locked poke-engine 0.0.48 archive. The base package version
still says 0.0.48, so **variant label plus wheel/source hashes are mandatory**. It is not the pinned
baseline and must never be reported as an unchanged upstream reproduction.

## Outcome

The extended 50-fixture suite agrees between pinned Showdown and Smogon calc on all 1,600 controlled
roll outputs (50 × 16 × regular/critical). Baseline maxima agree on 26/50 pairs; the variant agrees
on 33/50. Nine pairs change, 41 remain unchanged, and no pair's maximum absolute error increases
within these fixtures. All remaining 17 variant discrepancies are documented modifier-stage/
integer-arithmetic differences. **This does not establish exact full damage, transitions or Elo.**

| Case | Baseline regular / critical | Variant | Both oracle maxima |
|---|---:|---:|---:|
| Body Press, user Defense +2 | 1014 / 765 | 1014 / 1521 | 1014 / 1520 |
| Foul Play, target Attack +2 | 97 / 73 | 97 / 145 | 97 / 145 |
| Foul Play, target Attack/Defense +2 | 73 / 110 | 73 / 219 | 73 / 219 |
| Physical attack +2 into Unaware | 129 / 382 | 129 / 193 | 129 / 193 |
| Special attack +2 into Unaware | 468 / 1395 | 468 / 702 | 468 / 702 |
| Attacking Unaware vs Defense −2 | 153 / 450 | 153 / 229 | 152 / 228 |
| Attacking Unaware vs SpD −2 | 63 / 187 | 63 / 94 | 63 / 94 |
| Attacking Unaware vs defending Mold Breaker/Defense +2 | 57 / 166 | 111 / 166 | 111 / 166 |
| Attacking Unaware vs defending Mold Breaker/SpD +2 | 159 / 468 | 312 / 468 | 312 / 468 |

The Body Press stat bug is corrected but its critical maximum remains one HP high. Do not convert
“much closer” into an exact KO/safety claim. Ordinary and critical arithmetic changes are a separate
future patch, with their own oracle coverage.

## What changed, and why

The single Rust implementation file changed is `src/genx/damage_calc.rs`:

- Critical Foul Play retains positive target Attack boosts and still ignores negative boosts.
- Critical Body Press retains positive user Defense boosts and still ignores negative boosts.
- Defender Unaware applies to both regular and critical offensive-stat paths.
- Attacker Unaware applies to both regular and critical defensive-stat paths, including Psyshock's
  Defense override.
- Defending Mold Breaker does not suppress the attacker's Unaware. Its effect belongs to the
  Pokémon actually attacking; an attacking Mold Breaker bypasses defending Unaware as before.

These changes are in the shared damage-stat selection path, used by engine damage/transition
callers, not Python special-case postprocessing. A Rust regression checks 16 stat-selection tuples
independently of downstream damage rounding. The focused Rust damage suite has 39 passing tests;
all 227 library tests compiled by the declared Gen 9/Tera build pass. They are not an independent
Showdown transition conformance suite. Two additional project helper tests bring the Python suite
to **46 passed**.

## Harness correction and evidence history

The initial extended Unaware run found oracle disagreements. Source inspection showed that
Showdown `getDamage` expects the active move/attacker/target context normally set by `useMove`.
Without it, Unaware's `onAnyModifyBoost` handler cannot identify the attacking relationship.
The direct-hit oracle now establishes that context, runs the move type/modification events
(including Mold Breaker's `ignoreAbility`), and clears context after each controlled roll.

Primary pinned source locations: Showdown `sim/battle.ts:setActiveMove/suppressingAbility`,
`sim/battle-actions.ts:useMove/getDamage`, `data/abilities.ts:unaware/moldbreaker`; calculator
`calc/src/mechanics/gen789.ts:calculateAttackSMSSSV`. No internet documentation substitute was
used for the actual pinned code. This harness still does not perform a complete turn or accuracy
check, nor certify all abilities' pre-move event paths.

- `critical_stats_baseline_v1.json` is **quarantined harness evidence**: missing active context,
  not engine-failure evidence for its oracle-disagreement cases.
- V2 corrected context. All original 32 fixtures, oracle rolls and baseline maxima were checked
  against the older verified pilot and are unchanged. The earlier 32-case result remains valid in
  its measured scope; it never certified Unaware.
- Baseline v3 and variant v2 include complete classifications and expanded fixture/adjudication
  hashes, so changes to inherited fixture content cannot hide behind an unchanged child file hash.
- `compare_damage_reports.py` checks identical fixtures, engine-state hashes, oracle projections/
  stats/seeds/distributions, compiled oracle hashes and explicit engine labels. It recomputes max
  agreement and rejects worsening error or oracle mismatch. This is not a general-purpose proof
  that a patch improves playing strength.

The added sets are controlled probes, not an OU team-validation claim. One deliberately artificial
Umbreon/Unaware overlay isolates that attacking-ability interaction; it is not proposed as a legal
hidden opponent set. Other examples use Dondozo, Clodsire, Clefable and Haxorus with explicit spreads.

## Isolation and provenance

- Baseline source, wheel and `.venvs/foulplay-rebuild` are untouched; baseline verification still
  matches native/wrapper hashes against its original locked wheel.
- Variant source is a fresh extraction in `/tmp/pokeforge-critstats.zNs0P1/poke_engine-0.0.48`.
- Variant wheel is installed only in `.venvs/engine-critstats-v1`.
- Root `patches/poke_engine_0_0_48_critstats_v1.patch` is a small derivative patch with the MIT notice
  retained in `patches/README.md`. This does not select the project's overall release license.
- The checker verifies all 46 library Rust source hashes against the archive, allowing **only** the
  locked changed file for this variant. The reverse patch must apply cleanly. Installed native and
  Python wrapper must match the locked variant wheel. Runtime/version checks never accept an
  arbitrary modified engine solely because its package metadata says 0.0.48.

| Artifact | SHA256 |
|---|---|
| Base source archive | `070010686f2aedff11e25137e696e301ccd80fd57c805d255464067fc905ca12` |
| Variant patch | `e027305740f69e84312fb65452554b2a469b4a5162dd6127daa7859ff8c54178` |
| Patched Rust implementation incl. test | `7712a77f97b625cf48163d579244ece9de8b395a2af2589459b9c0bead0ff1d3` |
| Variant wheel | `9acc292309727153a2133a670e35a84ee5cb736fa73ca76ee5e843602b2ed936` |
| Baseline classified report | `55c3a2c6e53d54e7148f2bb3c0c8f3b428ba3ca91c1578cdb21901b7d2af4313` |
| Variant classified report | `8ba92cfcde598c181ad7ac0463f088f8a9e8c169e43a84d1640620bd6857dcac` |
| Paired report audit | `3b4c1513e5bd0b928763add687028686a0031110937e5db2a926f992ac5822b0` |

Reports are under `.artifacts/conformance/damage/`: `critical_stats_baseline_v3_adjudicated.json`,
`critical_stats_variant_v2_adjudicated.json`, `critical_stats_paired_audit_v1.json`.
The variant rerun reproduces all 50 state hashes, maxima, classifications and conditional supports,
with identical native/source/compiled-oracle hashes. Its paired audit again reports nine changed
and 41 unchanged pairs, with no increased maximum absolute error. Timing-dependent report hashes
are not expected to match; the repeat is not counted as another fixture population.

## Reproduce

From a fresh extraction of the locked archive, apply the stored patch with `git apply`, then run:

```bash
cargo test --locked --no-default-features --features terastallization --lib
maturin build \
  --release --locked --no-default-features --features poke-engine/terastallization \
  --interpreter python
```

Run the build in the isolated engine virtual environment used for the selected variant.

Build used maturin 1.12.6 and existing Cargo.lock. Wheel hashes are platform/toolchain-specific;
do not silently update the locked artifact to accept a different rebuild.

```bash
.venvs/engine-critstats-v1/bin/python scripts/check_damage_conformance.py \
  --calc /tmp/pokeforge-damage-calc-audit --engine-variant critstats-v1 \
  --engine-wheel /tmp/pokeforge-critstats.zNs0P1/poke_engine-0.0.48/target/wheels/poke_engine-0.0.48-cp312-cp312-manylinux_2_34_x86_64.whl \
  --engine-source /tmp/pokeforge-critstats.zNs0P1/poke_engine-0.0.48/src \
  --engine-sdist .artifacts/conformance/damage/poke_engine-0.0.48.tar.gz \
  --fixtures tests/fixtures/damage_critical_stats_v1.json \
  --adjudications tests/fixtures/damage_critical_stats_variant_adjudications_v1.json \
  --output .artifacts/conformance/damage/NEW_VARIANT.json

python scripts/compare_damage_reports.py \
  --baseline .artifacts/conformance/damage/critical_stats_baseline_v3_adjudicated.json \
  --variant .artifacts/conformance/damage/NEW_VARIANT.json \
  --output .artifacts/conformance/damage/NEW_COMPARISON.json
```

## Timing and remaining gates

Concurrent same-host microbenchmarks each made 2,500 warm damage calls. Baseline/variant p99 was
27.46/27.22 µs; mean 17.80/18.07 µs. These are similar-order local microbenchmarks, **not evidence
of a speedup or full end-to-end latency**. State conversion, neural/world batching, full transitions,
search, network and deadline handling are outside these measurements.

Full engine rolls, staged integer fidelity, accuracy/crit probabilities, residuals, joint-action
transitions, all frozen-team mechanics and robust live fallbacks remain open. No checkpoint weights,
live policies, public ladder or PokéAgent state changed; no training started. The engine/safety gate
is still **not passed**. Next work should expand joint-action conformance and required mechanic
coverage, with full stat-stage/roll support addressed before claiming an exact Safety Shield.
