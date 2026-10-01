// A real complete Showdown turn. No damage/randomizer/event overrides.
const fs = require('fs');
const path = require('path');
const {Battle, Dex} = require(path.join(path.resolve(process.argv[2]), 'dist/sim'));
const boostKeys = ['atk', 'def', 'spa', 'spd', 'spe', 'accuracy', 'evasion'];
const hazardKeys = ['stealthrock', 'spikes', 'toxicspikes', 'stickyweb'];
function project(battle, teams) {
  return [battle.p1, battle.p2].map((side, si) => ({
    active_index: teams[si].findIndex(spec => spec.name === side.active[0].name),
    hazards: Object.fromEntries(hazardKeys.map(id => [id,
      side.sideConditions[id] ? (side.sideConditions[id].layers || 1) : 0])),
    pokemon: teams[si].map(spec => {
      const p = side.pokemon.find(p => p.name === spec.name);
      const species = Dex.species.get(spec.species);
      return {species_id: species.id, hp: p.hp, maxhp: p.maxhp,
        status: p.hp === 0 ? '' : p.status, item: p.item, ability: p.ability,
        tera_type: p.terastallized || null,
        boosts: Object.fromEntries(boostKeys.map(k => [k, p.boosts[k]])),
        pp: p.moveSlots.map(m => m.pp),
        stats: {hp: p.maxhp, ...p.storedStats}, types: species.types,
        level: p.level, weight_kg: species.weightkg, nature: Dex.toID(spec.nature),
        evs: spec.evs, ivs: spec.ivs};
    })
  }));
}
function evaluate(fixture, seed) {
  const teams = fixture.teams;
  const battle = new Battle({formatid: 'gen9customgame@@@!Team Preview', seed,
    p1: {team: teams[0]}, p2: {team: teams[1]}});
  try {
    // Fixture setup is explicit; the subsequent makeChoices runs the ordinary event path.
    battle.field.clearWeather(); battle.field.clearTerrain();
    if (fixture.weather) battle.field.setWeather({Sun: 'sunnyday', Sand: 'sandstorm'}[fixture.weather], battle.p1.active[0]);
    for (let si = 0; si < 2; si++) {
      const side = [battle.p1, battle.p2][si];
      for (const spec of teams[si]) {
        const p = side.pokemon.find(p => p.name === spec.name);
        if (spec.hp != null) {
          if (!Number.isInteger(spec.hp) || spec.hp <= 0 || spec.hp > p.maxhp) throw Error('Invalid fixture HP');
          p.hp = spec.hp;
        }
        Object.assign(p.boosts, spec.boosts);
        if (spec.status) p.setStatus(spec.status);
        p.moveSlots.forEach(m => {m.pp = 8;});
        if (spec.preTera) battle.actions.terastallize(p);
      }
      for (const [id, layers] of Object.entries(fixture.hazards[si]))
        for (let n = 0; n < layers; n++) side.addSideCondition(id, side.active[0]);
    }
    const before = project(battle, teams), start = battle.log.length, weatherBefore = battle.field.weather;
    battle.makeChoices(...fixture.actions);
    if (battle.turn !== 2 && !battle.ended && battle.requestState !== 'switch')
      throw Error('Did not complete the requested joint turn');
    if (battle.log.slice(start).some(line => line.startsWith('|error|'))) throw Error('Invalid choices');
    return {seed, before, after: project(battle, teams),
      weather_before: weatherBefore, weather_after: battle.field.weather,
      log: battle.log.slice(start), turn: battle.turn, request_state: battle.requestState,
      ended: battle.ended};
  } finally {battle.destroy();}
}
module.exports = {project};
if (require.main === module) {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  process.stdout.write(JSON.stringify(input.fixtures.map(f => ({id: f.id,
    outcomes: input.seeds.map(seed => evaluate(f, seed))}))));
}
