"""Compare both pinned parsers, then check public delay/Encore observations against saved oracle truth.

Truth is consumed only by this offline checker, never injected into a framework or player transcript.
The controls cover the four scripted scenarios, not every delayed-effect or duration interaction.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_framework_states import checked_report_snapshot, SHOWDOWN_REVISION
from scripts.check_damage_conformance import tree_hash
from src.integration.contracts import hash_protocol_payload


def digest(path):
    return hash_protocol_payload(path.read_bytes())


def verify_public_delays(public, truth, perspective):
    """Independent oracle-field checks, restricted to these normal-turn scripted trajectories."""
    si = int(perspective[1]) - 1
    for relative, role in (("self", si), ("opponent", 1 - si)):
        own = relative == "self"
        for p in public[relative]["team"]:
            if not own and any(p[k] is not None for k in ("max_hp", "exact_stats", "nature", "evs", "ivs")):
                raise ValueError("Hidden opponent truth in canonical observation")
        wish = truth["slot_conditions"][role][0].get("wish")
        observed = public["field"][relative + "_wish"]
        if bool(wish) != bool(observed):
            raise ValueError("Wish presence differs from oracle")
        if wish:
            # Source's internal startingTurn is zero-based. These controls do not cross overflow.
            if observed["remaining_residuals"] != wish["startingTurn"] + 3 - truth["turn"]:
                raise ValueError("Wish residual clock differs from oracle")
            if observed["heal_hp"] != (int(wish["hp"]) if own else None):
                raise ValueError("Wish amount is incorrect or leaks opponent max HP")
        future = truth["slot_conditions"][1 - role][0].get("futuremove")
        observed = public["field"][relative + "_future_sight"]
        if bool(future) != bool(observed):
            raise ValueError("Future attack presence differs from oracle")
        if future and (observed["move_id"] != future["move"] or
                       observed["remaining_residuals"] != future["endingTurn"] + 2 - truth["turn"] or
                       observed["target_side"] != f'p{2 - role}' or observed["source_slot"] != 0):
            raise ValueError("Future attack source/target/clock differs from oracle")
        encore = truth["volatiles"][role].get("encore")
        active = public[relative]["active_slot"]
        observed = public[relative]["team"][active]["encore"] if active is not None else None
        if bool(encore) != bool(observed):
            raise ValueError("Encore presence differs from oracle")
        if encore and (observed["move_id"] != encore["move"] or not
                       observed["duration_residuals_lower"] <= encore["duration"] <= observed["duration_residuals_upper"]):
            raise ValueError("Encore move/duration falls outside public bound")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--oracle', type=Path, default=ROOT / '.artifacts/conformance/frozen_pool/multiturn_players_v2_room.json')
    parser.add_argument('--output-directory', type=Path, required=True)
    args = parser.parse_args()
    if args.output_directory.exists():
        parser.error('fresh output directory required')
    lock = tomllib.loads((ROOT / 'config/artifacts.lock.toml').read_text())
    pin = next(a for a in lock['artifacts'] if a['name'] == 'frozen-multiturn-player-fixtures-v2-room')
    if digest(args.oracle) != pin['sha256']:
        raise ValueError('Oracle artifact differs from locked player fixture report')
    oracle = json.loads(args.oracle.read_text())
    if oracle['showdown_revision'] != SHOWDOWN_REVISION or not oracle['team_preview_enabled']:
        raise ValueError('Wrong oracle profile/preview scope')
    showdown = ROOT / 'pokemon-showdown'
    revision = subprocess.check_output(['git', '-C', str(showdown), 'rev-parse', 'HEAD'], text=True).strip()
    dirty = subprocess.check_output(['git', '-C', str(showdown), 'status', '--short'], text=True).splitlines()
    compiled = tree_hash((str(p.relative_to(showdown)), p) for d in ('dist/sim', 'dist/data')
                         for p in (showdown / d).rglob('*.js'))
    if revision != SHOWDOWN_REVISION or dirty not in ([], [' M package-lock.json']) or compiled != oracle['compiled_showdown']:
        raise ValueError('Wish control simulator source/compiled pin differs')
    args.output_directory.mkdir(parents=True)
    evidence = []
    capture_index = {(c['scenario'], tuple(c['seed']), c['side']): c for c in oracle['player_captures']}
    for scenario in oracle['scenarios']:
        for n, run in enumerate(scenario['trajectories'], 1):
            for perspective in ('p1', 'p2'):
                capture = capture_index[(scenario['id'], tuple(run['seed']), perspective)]
                capture_path = ROOT / capture['path']
                if digest(capture_path) != capture['sha256']:
                    raise ValueError('Player transcript hash changed')
                reports = []
                for framework in ('foulplay', 'metamon'):
                    output = args.output_directory / f"{scenario['id']}-seed{n}-{perspective}-{framework}.json"
                    command = [str(ROOT / f'.venvs/{framework}-rebuild/bin/python'),
                        str(ROOT / 'scripts/check_framework_states.py'), '--framework', framework,
                        '--source', str(ROOT / '.artifacts/sources' / ('foul-play' if framework == 'foulplay' else 'metamon')),
                        '--capture', str(capture_path), '--output', str(output)]
                    if framework == 'metamon':
                        command += ['--compare', str(reports[0][0])]
                    process = subprocess.run(command, capture_output=True, text=True)
                    if process.returncode:
                        raise RuntimeError(process.stdout + process.stderr)
                    reports.append((output, json.loads(output.read_text())))
                expected = [run['transitions'][0]['before'], *[t['after'] for t in run['transitions']]]
                for _, report in reports:
                    if len(report['snapshots']) != len(expected) + 1:
                        raise ValueError('Missing preview/decision checkpoint')
                    preview = report['snapshots'][0]
                    checked_report_snapshot(preview)
                    if preview['phase'] != 'team_preview':
                        raise ValueError('Missing preview checkpoint')
                    for row, truth in zip(report['snapshots'][1:], expected, strict=True):
                        checked_report_snapshot(row)
                        if row['turn'] != truth['turn']:
                            raise ValueError('Oracle/parser checkpoint alignment differs')
                        verify_public_delays(row['public_state'], truth, perspective)
                evidence.append({'scenario': scenario['id'], 'seed': run['seed'], 'side': perspective,
                    'equal_semantic_snapshots': len(reports[0][1]['snapshots']),
                    'oracle_checked_decisions': len(expected),
                    'parser_reports': {framework: {'file': path.name, 'sha256': digest(path)}
                        for framework, (path, _) in zip(('foulplay', 'metamon'), reports, strict=True)}})
                print(f"{scenario['id']} seed{n} {perspective}: parser equality + public counters verified")

    # Actual complete-turn controls: legally change only the Wish user's HP IV, start at low HP.
    # This is controlled offline HP setup, not a live-game observation or a PRNG/event override.
    team = next(s['teams'] for s in oracle['scenarios'] if s['id'] == 'wish_heals_replacement')
    js = """
const {Battle, TeamValidator} = require(process.argv[1] + '/dist/sim');
const fs = require('fs'), teams = JSON.parse(fs.readFileSync(0, 'utf8'));
const out = [];
for (const iv of [31, 30]) {
  const pair = structuredClone(teams); pair[0][0].ivs.hp = iv;
  for (const t of pair) if (new TeamValidator('gen9ou').validateTeam(t)) throw Error('Invalid control team');
  const b = new Battle({formatid:'gen9ou@@@!Team Preview',seed:[19,4,7,13],p1:{team:pair[0]},p2:{team:pair[1]}});
  try {
    const p = b.p1.active[0]; p.hp = 20;
    b.makeChoices('move 2','move 3');
    const pending = b.p1.slotConditions[0].wish.hp, before = p.hp;
    b.makeChoices('move 4','move 3');
    const delta = p.hp - before;
    if (delta !== Math.floor(p.maxhp/2) || !b.log.some(l=>l.includes('[from] move: Wish'))) throw Error('Unexpected Wish control');
    out.push({hp_iv:iv,max_hp:p.maxhp,pending_hp:pending,actual_heal_hp:delta});
  } finally {b.destroy();}
}
process.stdout.write(JSON.stringify(out));
"""
    controls = json.loads(subprocess.check_output(['node', '-e', js, str(ROOT / 'pokemon-showdown')],
                         input=json.dumps(team), text=True))
    if {r['max_hp'] % 2 for r in controls} != {0, 1}:
        raise ValueError('Missing even/odd Wish controls')
    summary = {'schema_version': 1, 'oracle_sha256': digest(args.oracle), 'runner_sha256': digest(Path(__file__)),
        'adapter_sha256': digest(ROOT / 'src/integration/framework_state.py'), 'player_streams': len(evidence),
        'equal_semantic_snapshots': sum(e['equal_semantic_snapshots'] for e in evidence),
        'oracle_checked_decisions': sum(e['oracle_checked_decisions'] for e in evidence),
        'wish_rounding_controls': controls, 'evidence': evidence, 'gate_0b_passed': False,
        'limits': ['four scripted scenarios, two seeds, both players; shared public ledger',
                   'oracle truth used only for offline assertions, never parser/policy input',
                   'timer arithmetic oracle checks scoped to these histories; turn-overflow unsupported',
                   'modeled room envelope, not live networking/timing or complete mechanics conformance',
                   'Doom Desire code shares future-move mapping but no executed Doom Desire fixture here',
                   'no Rust rollout, neural policy integration, training or competitive-strength measurement']}
    with (args.output_directory / 'summary.json').open('x') as stream:
        json.dump(summary, stream, indent=2)
        stream.write('\n')
    print(f"{summary['equal_semantic_snapshots']} equal snapshots; {summary['oracle_checked_decisions']} oracle-checked public decision states")


if __name__ == '__main__':
    main()
