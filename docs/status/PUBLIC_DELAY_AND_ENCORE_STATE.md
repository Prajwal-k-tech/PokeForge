# Public delayed-effect and Encore state

Verified 2026-10-01. Offline canonical observation slice, **not Gate 0B/1 completion**.

`framework_state.py` now emits payload version 2 / `{framework}-state-v2`. The existing immutable
snapshot, stable identities and exact request/history hashes remain in use. Added fields come only
from player-visible history, own requests and the pinned Gen 9 rules. No oracle truth, native inferred
opponent stats or internal native duration guesses enter the observation.

## What the observation contains

- `field.self_wish` / `opponent_wish`: source's stable team slot, target field position 0, start turn
  and remaining residual phases. The own healing amount is `max_hp // 2`; the opponent amount stays
  `null`. Switching does not move the Wish to the source's bench slot. A failed attempt is removed;
  a failed re-use preserves the older pending Wish. A heal line clears it, and the residual clock
  also handles expiry at full HP without a heal line.
- `field.self_future_sight` / `opponent_future_sight`: **named by source side**, with explicit move
  ID, source's stable team slot, target side/field position, start turn and remaining residual phases.
  Setup uses `-start` evidence, not merely the attempted move. The effect survives source switching
  and ends on the recipient's `-end` or scheduled residual expiry. It is not a source volatile.
- `team[*].encore`: last observed locked move (or unknown), start turn and duration-clock bounds.
  A publicly observed prior action in the same turn establishes the four-residual initial duration;
  otherwise the initial bound is 3–4. PP exhaustion/items/switching can end it sooner. These are
  **clock bounds, not guaranteed numbers of future actions**. Public end/switch/faint evidence clears
  it. Native duration counters are not copied.

All delay clocks advance at `upkeep`, not on every request or replacement. Duplicate upkeep in one
turn is rejected. Chilly Reception's mid-turn replacement/wait therefore cannot spend a full turn
of a delayed effect. An observed single-turn protection activation is accepted only when the
corresponding effect has already been publicly established; arbitrary `-activate` events remain
unsupported.

Pinned primary sources: Showdown `a5df8274e85b0889bf2a9b3422a08b39732374fc`,
`data/moves.ts:Wish/FutureSight/DoomDesire/Encore`, `data/conditions.ts:futuremove`, and
`sim/battle.ts:heal`. Wish's stored amount can be fractional; this `Battle.heal` path truncates it.
This differs from ordinary move recovery's upstream rounding path and was checked separately.

## Executed evidence

The input remains locked `.artifacts/conformance/frozen_pool/multiturn_players_v2_room.json`, SHA256
`abc9b628ac7e265853729860c98cd85e26a8f8a463f4cc4185cdeea40e603cfe`.
It contains four actual frozen-team scenarios, two seeds each, both player streams, normal Team
Preview and an explicitly modeled pinned room-request envelope. It is **not a network capture**.

`check_multiturn_states.py` runs both real pinned native parsers in their isolated environments:
32 parser reports / 16 player streams / **80 matching semantic checkpoints**. Each non-preview
checkpoint is then checked against saved, privileged Showdown state: **64 player-perspective decision
states**, each checked for both parsers. These counts are not independent games or accuracy rates.
The public ledger is shared; matching parsers alone would not validate it. The separate oracle checks
test pending effect presence, Wish timing/private-amount exclusion, Future Sight source/target/timing,
and whether the actual Encore move/duration lies inside the public bounds.

Two additional complete-turn Showdown controls legally alter only Alomomola's HP IV and initialize
its HP low enough to avoid healing saturation. No PRNG or event implementation is overridden:

| HP IV | Max HP | Stored Wish amount | Actual heal |
|---|---:|---:|---:|
| 31 | 534 | 267 | 267 |
| 30 | 533 | 266.5 | 266 |

The initial implementation incorrectly rounded odd-HP Wish upward. Source review caught it before
live integration; the actual control independently confirms the corrected truncation. Original
recorded-battle regression: both parsers still agree on all **25 checkpoints** under payload v2.
The portable suite has **60 passing tests**, including timer lifecycle, failed Wish preservation,
opponent amount exclusion, late-turn rejection and an oracle-checker regression that rejects a
shared clock mistake/private healing amount.

## Reproduction and authoritative outputs

```bash
python scripts/check_multiturn_states.py \
  --output-directory .artifacts/conformance/states/NEW_MULTITURN_CHECK
PYTHONPATH=. python -m pytest -q tests
```

The output directory must be fresh. Source caches: `.artifacts/sources/foul-play` at
`6c467c081e862fb321adb405355beb41aba8e226` and `.artifacts/sources/metamon` at
`0a00a759c9a4382a2877088d828302ec294a05a5`. The checker verifies clean native pins, exact fixture
hashes and actual pinned/compiled Showdown before executing the extra rounding controls. The summary
hashes all 32 native reports; each report hashes its actual runtime files, adapter and transcript.

| Artifact | SHA256 |
|---|---|
| `.artifacts/conformance/states/multiturn_v4_verified/summary.json` | `71468e3bc810f28df9ad15a900e59047a4151ae1091878b59e9c1e13acabbb71` |
| `.artifacts/conformance/states/foulplay_v11_delay_regression.json` | `dcdd1d22f84678f08ea3d547c258bd60e9d3449e879f5800ca767f760ff001a0` |
| `.artifacts/conformance/states/metamon_v11_delay_regression.json` | `d67af00cf09e1d58088f16bfda31531f6eb2f88ade9a8b7b46e672eb1bf9d7be` |
| `src/integration/framework_state.py` | `c9d3f9f5341daad767f839cace6b980a522ebdee7a3f7885859472cb5a87f01c` |
| `scripts/check_multiturn_states.py` | `0e46ab16e8ba565e7db8374ed1088f9763bd4bcfa76db60e2537d30bfb18bcea` |

V2 single-parser diagnostics and the V3 batch are historical, not the authoritative checked batch.
The latter predates the fresh run with the explicit simulator-pin guard. They are not extra coverage.

## Limits and next boundary

- This checks four short scripted histories, not all cancellation, reflected/called moves, PP
  exhaustion, Mental Herb, full-HP/fainted-target delay resolution, simultaneous delays or long games.
- Delay use on turn 253 or later remains explicitly unsupported pending separate Gen 8+ overflow
  fixtures. Healing Wish/Lunar Dance and unrelated transformation/activation paths remain guarded.
- Doom Desire shares the source/target mapping, but **no executed Doom Desire fixture passed here**.
- Encore bounds are deliberately not called exact counters. The current scripts do not demonstrate
  every after-action/cannot-act/switch timing case or an actual end-of-duration transcript.
- The offline oracle checker contains scenario-specific alignment assumptions (including source
  slot 0); it is not a general game-state oracle. The full input report contains private state and
  must never be supplied to a live policy; only routed JSONL goes into a parser.
- Original baseline source, weights and engine wheels are unchanged. No Rust rollout, neural encoder,
  live variant attachment, training, public battle, PokéAgent submission or Elo measurement ran.

Next: targeted reachable controls for the diagnosed search-relevant engine defects, then broader
state identity/mechanic coverage and controlled agent evaluation under the canonical plan. Source,
checkpoint and team licenses retain the earlier recorded restrictions; no team redistribution is
authorized by this check.
