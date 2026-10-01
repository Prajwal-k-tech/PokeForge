// Actual pinned OU teams, complete first-turn event path, no PRNG/event overrides.
const fs = require('fs');
const path = require('path');
const {Battle, Dex, Teams, TeamValidator} = require(path.join(path.resolve(process.argv[2]), 'dist/sim'));
const {project} = require('./joint_turn_oracle.cjs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const stats = ['hp', 'atk', 'def', 'spa', 'spd', 'spe'];
function prepare(team, si) {
  return team.map((spec, pi) => ({...spec, name: `side${si + 1}slot${pi + 1}`,
    level: spec.level || 100, nature: spec.nature || 'Serious',
    evs: Object.fromEntries(stats.map(s => [s, spec.evs?.[s] || 0])),
    ivs: Object.fromEntries(stats.map(s => [s, spec.ivs?.[s] ?? 31]))}));
}
const teams = input.teams.map(record => {
  const parsed = Teams.import(record.export);
  const errors = new TeamValidator('gen9ou').validateTeam(parsed);
  if (errors || parsed.length !== 6) throw Error(`Invalid frozen team: ${record.file}: ${errors}`);
  return {file: record.file, sets: parsed};
});
if (input.mode === 'inventory') {
  const sets = teams.flatMap(t => t.sets);
  process.stdout.write(JSON.stringify({teams, inventory: {
    species: [...new Set(sets.map(s => Dex.species.get(s.species).id))].sort(),
    abilities: [...new Set(sets.map(s => Dex.toID(s.ability)))].sort(),
    items: [...new Set(sets.map(s => Dex.toID(s.item)))].sort(),
    moves: [...new Set(sets.flatMap(s => s.moves).map(m => Dex.toID(m)))].sort()
  }}));
} else {
  const results = [];
  for (const job of input.jobs) {
    const original = teams[job.team].sets;
    const rotation = [...original.slice(job.lead), ...original.slice(0, job.lead)];
    const opponent = teams[(job.team + 1) % teams.length].sets;
    const sets = [prepare(rotation, 0), prepare(opponent, 1)];
    const outcomes = [];
    for (const seed of input.seeds) {
      const battle = new Battle({formatid: 'gen9ou@@@!Team Preview', seed,
        p1: {team: sets[0]}, p2: {team: sets[1]}});
      try {
        // Known low-PP state avoids the engine's intentionally suppressed high-PP changes.
        for (const side of battle.sides) for (const p of side.pokemon)
          p.moveSlots.forEach(m => {m.pp = Math.min(8, m.maxpp);});
        const before = project(battle, sets);
        const fieldBefore = {weather: battle.field.weather, weather_turns: battle.field.weatherState.duration || 0,
          terrain: battle.field.terrain, terrain_turns: battle.field.terrainState.duration || 0};
        const initialVolatiles = battle.sides.map(s => Object.keys(s.active[0].volatiles).sort());
        const start = battle.log.length;
        const actions = [job.move === null ? 'switch 2' : `move ${job.move + 1}`, 'move 1'];
        battle.makeChoices(...actions);
        const log = battle.log.slice(start);
        if (log.some(l => l.startsWith('|error|'))) throw Error(`Invalid action in ${job.id}`);
        if (battle.turn !== 2 && !battle.ended && battle.requestState !== 'switch') throw Error('Incomplete joint action');
        outcomes.push({seed, before, after: project(battle, sets), field_before: fieldBefore,
          initial_volatiles: initialVolatiles, log, turn: battle.turn, request_state: battle.requestState,
          force_switch: battle.sides.map(s => Boolean(s.active[0].switchFlag) || s.active[0].fainted),
          final_volatiles: battle.sides.map(s => Object.keys(s.active[0].volatiles).sort()),
          field_after: {weather: battle.field.weather, terrain: battle.field.terrain}});
      } finally {battle.destroy();}
    }
    results.push({id: job.id, sets, outcomes});
  }
  process.stdout.write(JSON.stringify(results));
}
