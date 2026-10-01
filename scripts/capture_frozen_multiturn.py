"""Save independently executed Showdown trajectories for delayed/pivot/lock conformance work."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

if __package__:
    from .check_damage_conformance import ROOT, PINS, digest, tree_hash
    from .check_frozen_pool_turns import pool_records
    from .reproduce_foulplay_baseline import battle_protocol_record
else:
    from check_damage_conformance import ROOT, PINS, digest, tree_hash
    from check_frozen_pool_turns import pool_records
    from reproduce_foulplay_baseline import battle_protocol_record


def checked_player_records(messages, side, battle_tag, *, room_envelope=False):
    """Check routed player payloads, without copying any offline full-state truth into them."""
    records = []
    last_rqid = 1
    for message in messages:
        record = battle_protocol_record(f'>{battle_tag}\n{message}')
        if record is None or '|split|' in message or '|request|' in message and len(record['requests']) != 1:
            raise ValueError('Invalid player message boundary')
        for item in record['requests']:
            request = json.loads(item['payload'])
            if request.get('side', {}).get('id') != side:
                raise ValueError('Opponent private request in player stream')
            # Direct simulator requests lack rqid; the explicit offline room model supplies it.
            if room_envelope:
                rqid = request.get('rqid')
                if type(rqid) is not int or rqid <= last_rqid:
                    raise ValueError('Invalid modeled room request ID')
                last_rqid = rqid
            elif 'rqid' in request:
                raise ValueError('Unexpected synthesized server request ID')
        for line in message.splitlines():
            fields = line.split('|')
            if len(fields) >= 4 and fields[1] in {'switch', 'drag', '-damage', '-heal'}:
                if fields[2][:2] != side:
                    hp = fields[4] if fields[1] in {'switch', 'drag'} else fields[3]
                    if hp != '0 fnt' and hp.split()[0].split('/')[-1] != '100':
                        raise ValueError('Exact opponent HP leaked into player stream')
        records.append(record)
    first = next((json.loads(r['payload']) for c in records for r in c['requests']), None)
    if not first or not first.get('teamPreview') or len(first['side']['pokemon']) != 6:
        raise ValueError('Player stream does not begin with own six-member Team Preview request')
    return records


def validate(trajectories):
    for scenario in trajectories:
        for run in scenario['trajectories']:
            transitions = run['transitions']
            if len(transitions) != 3:
                raise ValueError('Incomplete trajectory')
            for previous, following in zip(transitions, transitions[1:]):
                if previous['after'] != following['before']:
                    raise ValueError('Discontinuous trajectory')
            if scenario['id'] == 'future_sight_survives_source_switch':
                if 'futuremove' not in transitions[0]['after']['slot_conditions'][1][0]:
                    raise ValueError('Missing pending Future Sight')
                if transitions[1]['after']['projection'][0]['active_index'] != 1:
                    raise ValueError('Source did not switch')
                if 'futuremove' in transitions[2]['after']['slot_conditions'][1][0]:
                    raise ValueError('Future Sight did not resolve')
            elif scenario['id'] == 'wish_heals_replacement':
                if 'wish' not in transitions[0]['after']['slot_conditions'][0][0]:
                    raise ValueError('Missing pending Wish')
                if transitions[1]['after']['projection'][0]['active_index'] != 1:
                    raise ValueError('Wish recipient did not switch')
                if not any('[from] move: Wish' in l for l in transitions[1]['log']):
                    raise ValueError('Wish did not heal replacement')
            elif scenario['id'] == 'chilly_reception_midturn_switch':
                if transitions[0]['after']['request_state'] != 'switch' or transitions[0]['after']['weather'] != 'snowscape':
                    raise ValueError('No snowy pivot request')
                if not transitions[0]['after']['requests'][1]['wait']:
                    raise ValueError('Opponent should wait during replacement')
                if transitions[1]['after']['turn'] != 2 or transitions[1]['after']['request_state'] != 'move':
                    raise ValueError('Pivot continuation did not complete turn')
            elif scenario['id'] == 'encore_changes_selected_move':
                if 'encore' not in transitions[1]['after']['volatiles'][1]:
                    raise ValueError('Encore not retained')
                if not any('|p2a: side2slot1|Calm Mind|' in l for l in transitions[1]['log']):
                    raise ValueError('Selected Moonblast was not changed to Calm Mind')
            else:
                raise ValueError('Unknown trajectory scenario')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seeds', type=int, default=8)
    parser.add_argument('--player-output-directory', type=Path,
                        help='Fresh directory for channel-filtered offline transcripts; enables normal Team Preview')
    args = parser.parse_args()
    if args.output.exists() or not 1 <= args.seeds <= 64:
        parser.error('new output and 1..64 seeds required')
    if args.player_output_directory and args.player_output_directory.exists():
        parser.error('player output directory must be new')
    showdown = ROOT / 'pokemon-showdown'
    if subprocess.check_output(['git', '-C', str(showdown), 'rev-parse', 'HEAD'], text=True).strip() != PINS['showdown']:
        raise ValueError('Wrong Showdown pin')
    dirty = subprocess.check_output(['git', '-C', str(showdown), 'status', '--short'], text=True).splitlines()
    if dirty not in ([], [' M package-lock.json']):
        raise ValueError('Unreviewed oracle source changes')
    compiled = tree_hash((str(p.relative_to(showdown)), p) for d in ('dist/sim', 'dist/data')
                         for p in (showdown / d).rglob('*.js'))
    verified = json.loads((ROOT / '.artifacts/conformance/damage/jointfix_v2_regression.json').read_text())
    if compiled != verified['compiled_oracles']['showdown']:
        raise ValueError('Compiled Showdown changed')
    manifest_path = ROOT / 'config/team_pools/gen9ou_control_v1.toml'
    _, records = pool_records(manifest_path, ROOT / '.artifacts/metamon/teams/competitive/gen9ou')
    fixture_path = ROOT / 'tests/fixtures/frozen_multiturn_v1.json'
    fixtures = json.loads(fixture_path.read_text())
    seeds = [[77, n, 56, 13] for n in range(1, args.seeds + 1)]
    oracle = ROOT / 'scripts/frozen_multiturn_oracle.cjs'
    results = json.loads(subprocess.check_output(['node', str(oracle), str(showdown)],
        input=json.dumps({'teams': records, 'scenarios': fixtures['scenarios'], 'seeds': seeds,
                          'capture_players': bool(args.player_output_directory)}), text=True))
    if [r['id'] for r in results] != [s['id'] for s in fixtures['scenarios']] or any(
        [t['seed'] for t in r['trajectories']] != seeds for r in results
    ):
        raise ValueError('Missing/reordered oracle scenarios or trajectories')
    validate(results)
    player_captures = []
    pending_files = []
    if args.player_output_directory:
        for scenario in results:
            for n, run in enumerate(scenario['trajectories'], 1):
                for si, messages in enumerate(run['player_messages'], 1):
                    tag = f"battle-gen9ou-{scenario['id']}-{n}"
                    capture = checked_player_records(messages, f'p{si}', tag, room_envelope=True)
                    source_requests = [r for r in run['simulator_requests'] if r['side'] == f'p{si}']
                    wrapped_requests = [json.loads(r['payload']) for c in capture for r in c['requests']]
                    if len(source_requests) != len(wrapped_requests):
                        raise ValueError('Lost simulator request')
                    for original, wrapped in zip(source_requests, wrapped_requests, strict=True):
                        if wrapped.pop('rqid') != original['rqid'] or wrapped != json.loads(original['payload']):
                            raise ValueError('Room model modified simulator request content')
                    target = args.player_output_directory / f"{scenario['id']}-seed{n}-p{si}.jsonl"
                    content = ''.join(json.dumps(row, separators=(',', ':')) + '\n' for row in capture)
                    pending_files.append((target, content))
                    player_captures.append({'scenario': scenario['id'], 'seed': run['seed'], 'side': f'p{si}',
                        'path': str(target.resolve().relative_to(ROOT)),
                        'sha256': hashlib.sha256(content.encode()).hexdigest(), 'messages': len(capture),
                        'requests': sum(len(c['requests']) for c in capture),
                        'transport': 'offline modeled RoomBattle rqid envelope, not a network capture'})
        args.player_output_directory.mkdir(parents=True)
        for target, content in pending_files:
            with target.open('x') as stream:
                stream.write(content)
    report = {'schema_version': 1, 'showdown_revision': PINS['showdown'], 'compiled_showdown': compiled,
              'manifest_sha256': digest(manifest_path), 'fixture_sha256': digest(fixture_path),
              'runner_sha256': digest(Path(__file__)), 'oracle_sha256': digest(oracle),
              'shared_projection_sha256': digest(ROOT / 'scripts/joint_turn_oracle.cjs'),
              'team_sha256': {r['file']: r['sha256'] for r in records}, 'seeds': seeds, 'scenarios': results,
              'player_captures': player_captures,
              'team_preview_enabled': bool(args.player_output_directory),
              'room_envelope_source_sha256': digest(showdown / 'server/room-battle.ts'),
              'gate_passed': False, 'limits': ['oracle-only trajectories, no engine/native parser comparison yet',
                'internal delayed-effect state is offline truth, not a player-visible belief',
                'scripted teams/actions, not policy games, rankings or complete stochastic conformance',
                'normal PP retained; previous low-PP pool probes are a different controlled state',
                'pinned local OU rules only; team redistribution rights unresolved',
                'player JSONL uses simulator send boundaries and a synthetic room header, not network capture',
                'raw simulator request bytes retained separately; player payloads add explicitly modeled room rqid',
                'full report retains privileged oracle truth and must never be passed to a live policy']}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print(f'Verified {len(results)} scenarios, {len(results) * len(seeds)} trajectories, three actions each.')


if __name__ == '__main__':
    main()
