// Offline fully specified state is an oracle artifact, never a live-agent observation.
const fs = require('fs');
const path = require('path');
const {Battle, Teams, TeamValidator} = require(path.join(path.resolve(process.argv[2]), 'dist/sim'));
const {extractChannelMessages} = require(path.join(path.resolve(process.argv[2]), 'dist/sim/battle'));
const {project} = require('./joint_turn_oracle.cjs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const pools = new Map(input.teams.map(t => {
  const sets = Teams.import(t.export);
  const errors = new TeamValidator('gen9ou').validateTeam(sets);
  if (errors || sets.length !== 6) throw Error('Invalid frozen team: ' + t.file);
  return [t.file, sets];
}));
function counters(state) {
  // Whitelist scalar/source fields: effect objects are circular and contain hidden truth.
  return Object.fromEntries(Object.entries(state).filter(([k, v]) =>
    ['duration', 'endingTurn', 'startingTurn', 'hp', 'move', 'sourceSlot', 'targetSlot'].includes(k) &&
    ['number', 'string', 'boolean'].includes(typeof v)));
}
function snapshot(battle, teams) {
  return {turn: battle.turn, request_state: battle.requestState, projection: project(battle, teams),
    requests: battle.sides.map(s => JSON.parse(JSON.stringify(s.activeRequest))),
    slot_conditions: battle.sides.map(s => s.slotConditions.map(slot => Object.fromEntries(
      Object.entries(slot).map(([id, state]) => [id, counters(state)])))),
    volatiles: battle.sides.map(s => Object.fromEntries(Object.entries(s.active[0].volatiles)
      .map(([id, state]) => [id, counters(state)]))),
    last_moves: battle.sides.map(s => s.active[0].lastMove?.id || null),
    weather: battle.field.weather, weather_state: counters(battle.field.weatherState)};
}
const result = [];
for (const scenario of input.scenarios) {
  const teams = scenario.teams.map((file, si) => {
    const pool = pools.get(file), lead = scenario.leads[si];
    if (!pool || !Number.isInteger(lead) || lead < 0 || lead >= 6) throw Error('Invalid team/lead');
    return [pool[lead], ...pool.filter((_, pi) => pi !== lead)].map((spec, pi) => ({...spec,
      name: `side${si + 1}slot${pi + 1}`, level: spec.level || 100, nature: spec.nature || 'Serious',
      evs: spec.evs || {}, ivs: spec.ivs || {}}));
  });
  const trajectories = [];
  for (const seed of input.seeds) {
    const playerMessages = [[], []];
    const simulatorRequests = [];
    let rqid = 1;
    // Match getPlayerStreams: updates are channel-filtered; sideupdates go only to their owner.
    const send = (type, data) => {
      if (!input.capture_players) return;
      if (Array.isArray(data)) data = data.join('\n');
      if (type === 'update') {
        const channels = extractChannelMessages(data, [1, 2]);
        for (let si = 0; si < 2; si++) if (channels[si + 1].length)
          playerMessages[si].push(channels[si + 1].join('\n'));
      } else if (type === 'sideupdate') {
        const cut = data.indexOf('\n'), side = data.slice(0, cut);
        if (!['p1', 'p2'].includes(side)) throw Error('Unexpected sideupdate owner');
        let payload = data.slice(cut + 1);
        if (payload.startsWith('|request|')) {
          // Offline model of pinned server/room-battle.ts receive: shared counter starts at 1.
          const raw = payload.slice(9), request = JSON.parse(raw);
          request.rqid = ++rqid;
          simulatorRequests.push({side, payload: raw, rqid});
          payload = '|request|' + JSON.stringify(request);
        }
        playerMessages[Number(side[1]) - 1].push(payload);
      }
      // Never expose the end payload: it contains both complete teams.
    };
    const battle = new Battle({formatid: input.capture_players ? 'gen9ou' : 'gen9ou@@@!Team Preview', seed,
      send, p1: {name: 'OfflineP1', team: teams[0]}, p2: {name: 'OfflineP2', team: teams[1]}});
    try {
      if (input.capture_players) {
        battle.sendUpdates();
        if (battle.requestState !== 'teampreview') throw Error('Missing normal Team Preview');
        battle.makeChoices('team 123456', 'team 123456');
        battle.sendUpdates();
      }
      const transitions = [];
      for (const choices of scenario.steps) {
        const before = snapshot(battle, teams), start = battle.log.length;
        for (let si = 0; si < 2; si++) {
          if (choices[si] === null) {
            if (battle.sides[si].requestState !== '') throw Error('Skipped an actionable request');
            continue;
          }
          if (!battle.sides[si].choose(choices[si])) throw Error(`Rejected ${scenario.id}: ${choices[si]}`);
        }
        if (!battle.allChoicesDone()) throw Error('Incomplete choices');
        battle.commitChoices();
        if (input.capture_players) battle.sendUpdates();
        const log = battle.log.slice(start);
        if (log.some(l => l.startsWith('|error|'))) throw Error('Server choice error');
        transitions.push({choices, before, after: snapshot(battle, teams), log});
      }
      const log = transitions.flatMap(t => t.log).join('\n');
      for (const marker of scenario.required_log) if (!log.includes(marker)) throw Error('Required mechanic absent: ' + marker);
      trajectories.push({seed, transitions, ...(input.capture_players ?
        {player_messages: playerMessages, simulator_requests: simulatorRequests} : {})});
    } finally {battle.destroy();}
  }
  result.push({id: scenario.id, teams, trajectories});
}
process.stdout.write(JSON.stringify(result));
