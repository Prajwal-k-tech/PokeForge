// Offline pinned Showdown / Smogon calculator oracle. One JSON batch on stdin.
const fs = require('fs');
const path = require('path');
const {performance} = require('perf_hooks');
const showdownPath = path.resolve(process.argv[2]);
const calcPath = path.resolve(process.argv[3]);
const {Battle, Dex} = require(path.join(showdownPath, 'dist/sim'));
const calc = require(path.join(calcPath, 'calc/dist'));
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const seed = [1, 2, 3, 4];
const weatherIDs = {Rain: 'raindance', Sun: 'sunnyday', Sand: 'sandstorm', Snow: 'snowscape'};
const terrainIDs = {Grassy: 'grassyterrain', Electric: 'electricterrain', Misty: 'mistyterrain', Psychic: 'psychicterrain'};

function set(pokemon, move) {
  return {...pokemon, moves: [move], teraType: pokemon.teraType || Dex.species.get(pokemon.species).types[0]};
}

function projection(p, spec) {
  const species = Dex.species.get(spec.species);
  return {species_id: species.id, level: p.level,
    stats: {hp: p.maxhp, ...p.storedStats}, types: species.types,
    weight_kg: species.weightkg, ability: p.ability, item: p.item,
    nature: Dex.toID(spec.nature), evs: spec.evs, ivs: spec.ivs,
    boosts: Object.fromEntries(Object.entries(p.boosts).filter(([, boost]) => boost !== 0)),
    status: p.status, tera_type: p.terastallized || null};
}

function evaluate(fixture) {
  const battle = new Battle({formatid: 'gen9customgame@@@!Team Preview', seed,
    p1: {team: [set(fixture.attacker, fixture.move)]},
    p2: {team: [set(fixture.defender, 'Splash')]}});
  try {
    const a = battle.p1.active[0], d = battle.p2.active[0];
    battle.field.clearWeather(); battle.field.clearTerrain();
    if (fixture.weather) battle.field.setWeather(weatherIDs[fixture.weather], a);
    if (fixture.terrain) battle.field.setTerrain(terrainIDs[fixture.terrain], a);
    if (battle.field.weather !== (weatherIDs[fixture.weather] || '') ||
        battle.field.terrain !== (terrainIDs[fixture.terrain] || '')) throw Error('Field mapping differs');
    for (const [poke, spec] of [[a, fixture.attacker], [d, fixture.defender]]) {
      Object.assign(poke.boosts, spec.boosts);
      poke.status = spec.status;
      if (spec.teraType) battle.actions.terastallize(poke);
    }
    for (const screen of fixture.screens) battle.p2.addSideCondition(screen, d);
    const sdStarted = performance.now();
    const sd = {};
    for (const crit of [false, true]) {
      const rolls = [];
      for (let roll = 85; roll <= 100; roll++) {
        // Enumerate the official randomizer's exact integer support, not approximate scaling
        // of the maximum final damage. Only this stage is controlled; all damage events run.
        battle.randomizer = base => battle.trunc(battle.trunc(base * roll) / 100);
        const move = battle.dex.getActiveMove(fixture.move);
        move.willCrit = crit;
        // getDamage is called inside useMove's active context. Ability event handlers such
        // as Unaware need these actor/target bindings; Mold Breaker is set by ModifyMove.
        battle.setActiveMove(move, a, d);
        battle.singleEvent('ModifyType', move, null, a, d, move, move);
        battle.singleEvent('ModifyMove', move, null, a, d, move, move);
        battle.runEvent('ModifyType', a, d, move, move);
        battle.runEvent('ModifyMove', a, d, move, move);
        let damage;
        try {damage = battle.actions.getDamage(a, d, move, true);}
        finally {battle.clearActiveMove(true);}
        if (damage === undefined || damage === null) throw Error('No direct damage result');
        rolls.push(damage === false ? 0 : damage);
      }
      sd[crit ? 'critical' : 'regular'] = rolls;
    }
    const sdMS = performance.now() - sdStarted;
    const field = new calc.Field({gameType: 'Singles', weather: fixture.weather || undefined,
      terrain: fixture.terrain || undefined, defenderSide: {
        isReflect: fixture.screens.includes('reflect'), isLightScreen: fixture.screens.includes('lightscreen'),
        isAuroraVeil: fixture.screens.includes('auroraveil') }});
    const cp = spec => new calc.Pokemon(9, spec.species, {...spec, teraType: spec.teraType || undefined});
    const ca = cp(fixture.attacker), cd = cp(fixture.defender);
    const calcStarted = performance.now();
    const calculated = {};
    for (const crit of [false, true]) {
      const result = calc.calculate(9, cp(fixture.attacker), cp(fixture.defender),
        new calc.Move(9, fixture.move, {isCrit: crit}), field.clone());
      if (typeof result.damage === 'number') calculated[crit ? 'critical' : 'regular'] = Array(16).fill(result.damage);
      else if (result.damage.length === 16 && result.damage.every(Number.isFinite))
        calculated[crit ? 'critical' : 'regular'] = result.damage;
      else throw Error('Fixture needs multi-hit/variable-damage semantics not supported by this pilot');
    }
    return {id: fixture.id, showdown: sd, smogon_calc: calculated,
      state: {attacker: projection(a, fixture.attacker), defender: projection(d, fixture.defender),
        field: {weather: battle.field.weather, terrain: battle.field.terrain,
          screens: Object.keys(battle.p2.sideConditions).filter(id => ['reflect', 'lightscreen', 'auroraveil'].includes(id))}},
      calc_stats: {attacker: ca.rawStats, defender: cd.rawStats}, seed,
      latency_ms: {showdown_32_controlled_queries: sdMS, calc_two_distributions: performance.now() - calcStarted}};
  } finally {battle.destroy();}
}
process.stdout.write(JSON.stringify(input.map(evaluate)));
