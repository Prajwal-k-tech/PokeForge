"""Observation-preserving projections of the pinned frameworks' battle objects.

The context records provenance/identity information lost by either framework. Current battle
mechanics are read independently from each native parser; inferred hidden sets never cross here.
This is a checked Gen 9 singles slice, not an all-mechanics parser or a deterministic world.
"""

from __future__ import annotations

import json
import math
from copy import deepcopy

from .contracts import BattlePhase, BattleSnapshot, TeamSlot, canonical_json, hash_history, hash_protocol_payload
from .showdown_request import legal_actions_from_request

STATS = ("atk", "def", "spa", "spd", "spe")
BOOSTS = (*STATS, "accuracy", "evasion")
STACKING = {"spikes", "toxicspikes"}
TERRAINS = {"electricterrain", "grassyterrain", "mistyterrain", "psychicterrain"}
SINGLE_TURN = {"roost", "protect", "detect", "endure", "spikyshield", "kingsshield",
               "banefulbunker", "silktrap", "burningbulwark", "obstruct"}
ROOMS = {"trickroom", "magicroom", "wonderroom"}
FUTURE_MOVES = {"futuresight", "doomdesire"}


def normalized(value):
    return "".join(c.lower() for c in value if c.isascii() and c.isalnum())


def named(value):
    return normalized(value.name) if hasattr(value, "name") else normalized(str(value))


def knowledge(value, *, observed):
    if not observed:
        return {"state": "unknown", "id": None}
    return {"state": "known" if value else "known_empty", "id": value or None}


def displayed_hp(condition, *, exact):
    """Pinned Gen 9 HP Percentage Mod, including Showdown's special 99% bucket."""
    tokens = condition.split()
    if not tokens:
        raise ValueError("empty health observation")
    status = tokens[1] if len(tokens) > 1 else ""
    if tokens[0] == "0" and status == "fnt":
        return {"display": condition, "numerator": 0, "denominator": None,
                "fraction_lower": 0.0, "fraction_upper": 0.0,
                "lower_inclusive": True, "upper_inclusive": True, "exact": True}
    numerator, denominator = (int(v) for v in tokens[0].split("/"))
    if denominator <= 0 or not 0 < numerator <= denominator:
        raise ValueError("invalid live health observation")
    fraction = numerator / denominator
    if exact:
        low, high, low_inc, high_inc = fraction, fraction, True, True
    else:
        if denominator != 100:
            raise ValueError("this slice requires Gen 9 HP Percentage Mod, not pixel/exact opponent HP")
        if numerator == 100:
            low, high, low_inc, high_inc = 1.0, 1.0, True, True
        elif numerator == 99:
            low, high, low_inc, high_inc = .98, 1.0, False, False
        else:
            low, high, low_inc, high_inc = (numerator - 1) / 100, fraction, False, True
    return {"display": condition, "numerator": numerator, "denominator": denominator,
            "fraction_lower": low, "fraction_upper": high,
            "lower_inclusive": low_inc, "upper_inclusive": high_inc, "exact": exact or numerator == 100}


class TranscriptContext:
    """Player-visible identity/evidence ledger; no species stats or inferred hidden sets."""

    def __init__(self, battle_tag, *, format_id, rules_revision):
        self.battle_tag, self.format_id, self.rules_revision = battle_tag, format_id, rules_revision
        self.lines = []
        self.rules = []
        self.preview = {"p1": [], "p2": []}
        self.own_idents = ()
        self.identities = {}
        self.evidence = {}
        self.hp = {}
        self.statuses = {}
        self.own_maxhp = {}
        self.move_events = []
        self.damage_events = []
        self.reveal_events = []
        self.side_conditions = {"p1": {}, "p2": {}}
        self.side_started = {"p1": {}, "p2": {}}
        self.weather_started = None
        self.observed_weather = None
        self.field_started = {}
        self.turn = 0
        self.perspective = None
        self.payload = None
        self.finished = False
        self.unsupported = set()
        self.adapter_notes = []
        self.singleturn_effects = {}
        self.persistent_effects = {}
        self.wishes = {}
        self.future_moves = {}
        self.encores = {}
        self.last_moves = {}
        self.acted_turns = {}
        self.last_upkeep_turn = -1

    @property
    def request(self):
        return json.loads(self.payload)

    @property
    def request_slots(self):
        members = self.request.get("side", {}).get("pokemon", [])
        return tuple(self.own_idents.index(p["ident"]) for p in members)

    def slot_for_ident(self, ident, species=None):
        role = ident[:2]
        nickname = ident.partition(":")[2].strip()
        key = (role, nickname)
        if key not in self.identities:
            if role == self.perspective:
                own_ident = f"{role}: {nickname}"
                if own_ident not in self.own_idents:
                    raise ValueError("own identity not present in original request preview")
                slot = self.own_idents.index(own_ident)
            else:
                candidates = [i for i, detail in enumerate(self.preview[role])
                              if normalized(detail.split(",", 1)[0]) == species]
                if len(candidates) != 1:
                    raise ValueError("unresolved/ambiguous opponent preview identity")
                slot = candidates[0]
                if (role, slot) in self.identities.values():
                    raise ValueError("multiple opponent identities mapped to one preview slot")
            self.identities[key] = (role, slot)
        return self.identities[key]

    def _reveal(self, ident, field, value, event):
        key = self.slot_for_ident(ident)
        self.evidence.setdefault(key, {})[field] = value
        self.reveal_events.append({"turn": self.turn, "side": key[0], "slot": key[1],
                                   "field": field, "value": value, "event": event})

    def _health(self, key, condition):
        self.hp[key] = {"condition": condition, "turn": self.turn}
        tokens = condition.split()
        self.statuses[key] = None if condition.endswith(" fnt") else tokens[1] if len(tokens) > 1 else "none"
        if key[0] == self.perspective and not condition.endswith(" fnt"):
            self.own_maxhp[key[1]] = displayed_hp(condition, exact=True)["denominator"]

    def _upkeep(self):
        if self.last_upkeep_turn == self.turn:
            raise ValueError("duplicate upkeep would advance public timers twice")
        self.last_upkeep_turn = self.turn
        self.singleturn_effects.clear()
        for effects in (self.wishes, self.future_moves):
            for role, effect in list(effects.items()):
                effect["remaining_residuals"] -= 1
                if effect["remaining_residuals"] == 0:
                    del effects[role]
        for effect in self.encores.values():
            # Bounds concern the duration clock; unknown PP can terminate the effect earlier.
            effect["duration_residuals_lower"] = max(1, effect["duration_residuals_lower"] - 1)
            effect["duration_residuals_upper"] -= 1
            if effect["duration_residuals_upper"] < 1:
                raise ValueError("Encore clock expired without a public end event")

    def consume(self, message):
        if not message or message.splitlines()[0] != ">" + self.battle_tag:
            raise ValueError("message belongs to a different battle")
        if sum(line.startswith("|request|") and line != "|request|" for line in message.split("\n")[1:]) > 1:
            raise ValueError("multiple requests in one message need sequential snapshot handling")
        for line in message.split("\n")[1:]:
            self.lines.append(line)
            if not line.startswith("|"):
                continue
            event = line.split("|")
            kind = event[1]
            if kind == "request" and event[2]:
                payload = line[len("|request|"):]
                request = json.loads(payload)
                if not self.own_idents:
                    if not request.get("teamPreview"):
                        raise ValueError("first request must establish six own preview slots")
                    self.perspective = request["side"]["id"]
                    self.own_idents = tuple(p["ident"] for p in request["side"]["pokemon"])
                    if len(self.own_idents) != 6 or len(set(self.own_idents)) != 6:
                        raise ValueError("requires six unique own preview identities")
                    for p in request["side"]["pokemon"]:
                        self.slot_for_ident(p["ident"])
                self.payload = payload
                if {p["ident"] for p in request.get("side", {}).get("pokemon", [])} != set(self.own_idents):
                    raise ValueError("own request identity set changed")
                for p in request["side"]["pokemon"]:
                    key = self.slot_for_ident(p["ident"])
                    self._health(key, p["condition"])
                    self.evidence.setdefault(key, {}).update(item=p.get("item") or None, ability=p.get("ability"))
                    if p.get("reviving"):
                        self.unsupported.add("revival")
                if any(m.get("id") == "recharge" for a in request.get("active", []) for m in a.get("moves", [])):
                    self.unsupported.add("recharge-action")
            elif kind == "rule":
                self.rules.append(event[2])
            elif kind == "clearpoke":
                if self.payload is not None:
                    raise ValueError("preview reset after identity establishment")
                self.preview = {"p1": [], "p2": []}
            elif kind == "poke":
                self.preview[event[2]].append(event[3])
            elif kind == "turn":
                self.turn = int(event[2])
            elif kind in {"switch", "drag"}:
                key = self.slot_for_ident(event[2], normalized(event[3].split(",", 1)[0]))
                self._health(key, event[4])
                self.singleturn_effects = {k: v for k, v in self.singleturn_effects.items() if k[0] != key[0]}
                self.persistent_effects = {k: v for k, v in self.persistent_effects.items() if k[0] != key[0]}
                self.encores = {k: v for k, v in self.encores.items() if k[0] != key[0]}
                self.acted_turns[key] = self.turn
                self.last_moves.pop(key, None)  # Showdown clears lastMove on switching out/in.
                if any("Baton Pass" in v or "Shed Tail" in v for v in event[5:]):
                    self.unsupported.add("transferred-volatiles")
            elif kind in {"-damage", "-heal"}:
                key = self.slot_for_ident(event[2])
                self._health(key, event[3])
                self.damage_events.append({"turn": self.turn, "side": key[0], "slot": key[1],
                                           "kind": kind, "condition": event[3], "annotations": event[4:]})
                if kind == "-heal" and "[from] move: Wish" in event[4:]:
                    self.wishes.pop(key[0], None)
            elif kind == "faint":
                key = self.slot_for_ident(event[2])
                self._health(key, "0 fnt")
                self.singleturn_effects.pop(key, None)
                self.persistent_effects.pop(key, None)
                self.encores.pop(key, None)
            elif kind in {"-status", "-curestatus"}:
                self.statuses[self.slot_for_ident(event[2])] = event[3] if kind == "-status" else "none"
            elif kind == "move":
                key = self.slot_for_ident(event[2])
                move_id = normalized(event[3])
                self.last_moves[key] = move_id
                self.acted_turns[key] = self.turn
                self.move_events.append({"turn": self.turn, "side": key[0], "slot": key[1],
                                         "move_id": move_id, "annotations": event[4:]})
                if move_id == "wish" and "[still]" not in event[4:] and key[0] not in self.wishes:
                    # Failed attempts are removed by -fail. A failed re-use cannot overwrite a pending Wish.
                    maximum = self.own_maxhp.get(key[1]) if key[0] == self.perspective else None
                    self.wishes[key[0]] = {"source_slot": key[1], "target_position": 0,
                        "started_turn": self.turn, "remaining_residuals": 2,
                        "heal_hp": maximum // 2 if maximum is not None else None}
                if move_id in {"wish", *FUTURE_MOVES} and self.turn >= 253:
                    self.unsupported.add("late-turn-delay-clock")  # Gen 8+ overflow needs separate fixtures.
                if move_id in {"healingwish", "lunardance"}:
                    self.unsupported.add("delayed-move-counters")
                if any(v.startswith("[from]") for v in event[4:]):
                    self.unsupported.add("called-or-reflected-move")
            elif kind == "cant":
                self.acted_turns[self.slot_for_ident(event[2])] = self.turn
            elif kind == "-fail":
                key = self.slot_for_ident(event[2])
                wish = self.wishes.get(key[0])
                if wish and wish["started_turn"] == self.turn and wish["source_slot"] == key[1] and self.last_moves.get(key) == "wish":
                    self.wishes.pop(key[0])
            elif kind in {"-item", "-enditem", "-ability", "-terastallize"}:
                field = {"-item": "item", "-enditem": "item", "-ability": "ability", "-terastallize": "tera"}[kind]
                self._reveal(event[2], field, None if kind == "-enditem" else normalized(event[3]), kind)
                if kind == "-enditem":
                    self._reveal(event[2], "removed_item", normalized(event[3]), kind)
                if any("[from] move:" in v or "[from] ability:" in v for v in event[4:]):
                    self.unsupported.add("item-or-ability-transfer")
            elif kind in {"-sidestart", "-sideend"}:
                role, condition = event[2][:2], normalized(event[3].removeprefix("move: "))
                if kind == "-sideend":
                    self.side_conditions[role].pop(condition, None)
                    self.side_started[role].pop(condition, None)
                else:
                    previous = self.side_conditions[role].get(condition, 0)
                    self.side_conditions[role][condition] = previous + 1 if condition in STACKING else 1
                    self.side_started[role].setdefault(condition, self.turn)
            elif kind == "-weather":
                self.observed_weather = normalized(event[2]) if event[2] != "none" else None
                if "[upkeep]" not in event[3:]:
                    self.weather_started = self.turn if event[2] != "none" else None
            elif kind in {"-fieldstart", "-fieldend"}:
                field = normalized(event[2].removeprefix("move: "))
                if field not in TERRAINS | {"trickroom", "gravity"}:
                    self.unsupported.add("unhandled-field-effect")
                if kind == "-fieldend":
                    self.field_started.pop(field, None)
                else:
                    self.field_started[field] = self.turn
            elif kind == "-singleturn":
                effect = normalized(event[3].removeprefix("move: "))
                if effect not in SINGLE_TURN:
                    self.unsupported.add("unhandled-singleturn-effect")
                self.singleturn_effects.setdefault(self.slot_for_ident(event[2]), set()).add(effect)
            elif kind == "upkeep":
                self._upkeep()
            elif kind in {"-start", "-end"}:
                condition = normalized(event[3].removeprefix("move: ").removeprefix("ability: "))
                key = self.slot_for_ident(event[2])
                effects = self.persistent_effects.setdefault(key, set())
                if condition in FUTURE_MOVES:
                    # -start identifies the source; -end identifies the recipient's current occupant.
                    if kind == "-start":
                        self.future_moves[key[0]] = {"move_id": condition, "source_slot": key[1],
                            "target_side": "p2" if key[0] == "p1" else "p1", "target_position": 0,
                            "started_turn": self.turn, "remaining_residuals": 3}
                    else:
                        source_role = "p2" if key[0] == "p1" else "p1"
                        pending = self.future_moves.get(source_role)
                        if not pending or pending["move_id"] != condition:
                            raise ValueError("Future attack ended without its observed setup")
                        self.future_moves.pop(source_role)
                elif kind == "-start":
                    effects.add(condition)
                else:
                    effects.discard(condition)
                if condition == "encore":
                    if kind == "-end":
                        self.encores.pop(key, None)
                    else:
                        already_acted = self.acted_turns.get(key) == self.turn
                        self.encores[key] = {"move_id": self.last_moves.get(key), "started_turn": self.turn,
                            "duration_residuals_lower": 4 if already_acted else 3,
                            "duration_residuals_upper": 4,
                            "duration_scope": "clock bound, may end early from PP/item/switch"}
            elif kind in {"win", "tie"}:
                self.finished = True
            if kind in {"replace", "detailschange", "-formechange", "-transform", "-sethp",
                        "-swapsideconditions", "-cureteam", "-endability", "-activate", "-singlemove", "-prepare"}:
                # Unlike two-turn moves, this is an announcement in the same turn, not a charge lock.
                # Pinned Showdown moves.ts:chillyreception.onBeforeMove; its actual pivot stays request-bound.
                if not (kind == "-prepare" and normalized(event[3]) == "chillyreception"
                        and event[4:] == ["[premajor]"]) and not (
                        kind == "-activate" and len(event) == 4 and
                        normalized(event[3].removeprefix("move: ")) in
                        self.singleturn_effects.get(self.slot_for_ident(event[2]), set()) & SINGLE_TURN):
                    self.unsupported.add(kind)
            if kind in {"-start", "-end"} and normalized(event[3]) in {"gastroacid", "skillswap", "typechange", "typeadd", "transform"}:
                self.unsupported.add("temporary-ability-or-type-change")
            # Item/ability sources are observations too, not only explicit reveal events.
            for annotation in event[3:]:
                for field in ("item", "ability"):
                    prefix = f"[from] {field}: "
                    if annotation.startswith(prefix):
                        owners = [v.removeprefix("[of] ") for v in event[3:] if v.startswith("[of] ")]
                        owner = owners[0] if owners else event[2]
                        if kind == "-heal" and field == "ability" and normalized(annotation.removeprefix(prefix)) != "hospitality":
                            owner = event[2]  # Water Absorb etc. belongs to the healed Pokemon.
                        if owner[:2] in {"p1", "p2"} and ":" in owner:
                            if field == "item" and kind == "-heal" and self.evidence.get(self.slot_for_ident(owner), {}).get("item", "unknown") is None:
                                # Berry healing can be announced after the item has been consumed.
                                continue
                            self._reveal(owner, field, normalized(annotation.removeprefix(prefix)), kind)


def _native_pokemon(framework, battle, role, context):
    own = role == context.perspective
    if framework == "foulplay":
        side = battle.user if own else battle.opponent
        members = [p for p in [side.active, *side.reserve] if p is not None]
        active = side.active
        lookup = {}
        for p in members:
            if own:
                key = context.slot_for_ident(f"{role}: {p.nickname}")
            else:
                candidates = [i for i, s in enumerate(context.preview[role]) if normalized(s.split(",", 1)[0]) == p.name]
                if len(candidates) != 1:
                    raise ValueError("native FoulPlay species does not resolve to one preview slot")
                key = role, candidates[0]
            lookup[key[1]] = p
        return lookup, active
    if framework != "metamon":
        raise ValueError("unknown framework")
    team = battle.team if own else battle.opponent_team
    lookup = {}
    if own:
        for ident, p in team.items():
            lookup[context.slot_for_ident(ident)[1]] = p
    else:
        # poke-env keeps unrevealed preview objects outside its post-preview opponent_team.
        for p in [*battle._teampreview_opponent_team, *team.values()]:
            candidates = [i for i, detail in enumerate(context.preview[role])
                          if normalized(detail.split(",", 1)[0]) == p.species]
            if len(candidates) != 1:
                raise ValueError("native Metamon species does not resolve to one preview slot")
            lookup[candidates[0]] = p
    return lookup, battle.active_pokemon if own else battle.opponent_active_pokemon


def _project_member(framework, p, slot, role, active, context, own_request):
    own = role == context.perspective
    preview = normalized(context.preview[role][slot].split(",", 1)[0])
    evidence = context.evidence.get((role, slot), {})
    observation = context.hp.get((role, slot))
    if own:
        condition, observed_turn = observation["condition"], observation["turn"]
    elif observation:
        condition, observed_turn = observation["condition"], observation["turn"]
    else:
        condition, observed_turn = None, None
    if p is None:
        raise ValueError("native parser omitted preview member")
    is_active = p is active and not context.request.get("teamPreview")
    observed = own or observation is not None
    if framework == "foulplay":
        species, level, status = p.name, p.level, str(p.status) if p.status else ""
        item = p.item if p.item != "unknownitem" else None
        ability, tera, tera_type = p.ability, p.terastallized, p.tera_type
        base_types = list(p.types)
        effective_types = [tera_type] if tera else base_types
        boosts = {s: int(p.boosts.get({"atk": "attack", "def": "defense", "spa": "special-attack",
                  "spd": "special-defense", "spe": "speed"}.get(s, s), 0)) for s in BOOSTS}
        move_ids = {m.name for m in p.moves}
        stats = {s: p.stats[{"atk": "attack", "def": "defense", "spa": "special-attack", "spd": "special-defense", "spe": "speed"}[s]] for s in STATS}
        # Upstream's decision-time request update parses `0 fnt` as max_hp=0.
        # It is not evidence that the Pokemon's true maximum HP is zero.
        if p.max_hp == 0 and p.hp != 0:
            raise ValueError("native nonzero HP has zero denominator")
        hp_fraction = p.hp / p.max_hp if p.max_hp else 0.0
        native_hp, native_maxhp = p.hp, p.max_hp
        volatiles = sorted(normalized(v) for v in p.volatile_statuses)
    else:
        species, level, status = p.species, p.level, named(p.status) if p.status else ""
        item, ability, tera, tera_type = p.item, p.ability, p.is_terastallized, named(p.tera_type) if p.tera_type else None
        # Native types includes Tera replacement; underlying original type getters do not.
        base_types = [named(t) for t in (p._type_1, p._type_2) if t is not None]
        effective_types = [named(t) for t in p.types]
        boosts = {s: int(p.boosts.get(s, 0)) for s in BOOSTS}
        move_ids, stats = set(p.moves), {s: p.stats[s] for s in STATS}
        hp_fraction, native_hp, native_maxhp = p.current_hp_fraction, p.current_hp, p.max_hp
        volatiles = sorted(named(v) for v in p.effects)
    if species != preview:
        raise ValueError("native form differs from preview; form/Illusion mapping not yet supported")
    health = displayed_hp(condition, exact=own) if condition else None
    fainted = condition.endswith(" fnt") if condition else None
    if health and (own or is_active or fainted):
        expected_fraction = 0 if fainted else health["numerator"] / health["denominator"]
        if not math.isclose(hp_fraction, expected_fraction, abs_tol=1e-8):
            raise ValueError(f"native displayed HP drift: {species}: {hp_fraction} vs {expected_fraction}")
    if observed and not fainted and (status or "none") != context.statuses[(role, slot)]:
        raise ValueError("native status differs from current visible evidence")
    if own:
        if not fainted and (native_hp != health["numerator"] or native_maxhp != health["denominator"]):
            raise ValueError("native own exact HP differs from current request")
        if stats != own_request["stats"] or item != evidence["item"]:
            raise ValueError("native own stats/item differ from current request")
        if ability != evidence["ability"]:
            raise ValueError("native own ability differs from current request")
        private_tera = normalized(own_request.get("teraType", "")) or None
        if tera_type is not None and tera_type != private_tera:
            raise ValueError("native own Tera type differs from current request")
        if tera_type is None and private_tera is not None:
            context.adapter_notes.append({"slot": slot, "side": role, "field": "tera_type",
                                          "source": "exact own request", "reason": "native parser omits private teraType"})
            tera_type = private_tera
        moves = []
        active_moves = context.request.get("active", [{}])[0].get("moves", []) if is_active and not context.finished else []
        for index, move in enumerate(own_request["moves"]):
            if move not in move_ids:
                raise ValueError("native own moveset omitted request move")
            detail = next((m for m in active_moves if m["id"] == move), {})
            moves.append({"slot": index, "id": move, "pp": detail.get("pp"), "max_pp": detail.get("maxpp"),
                          "disabled": detail.get("disabled")})
    else:
        stats = None
        revealed = sorted({e["move_id"] for e in context.move_events if (e["side"], e["slot"]) == (role, slot)})
        if not set(revealed) <= move_ids:
            raise ValueError("native opponent moves omit a visible move")
        moves = [{"slot": None, "id": m, "pp": None, "max_pp": None, "disabled": None} for m in revealed]
        if "item" in evidence and item != evidence["item"]:
            raise ValueError("native opponent item differs from visible evidence")
        if "ability" in evidence and ability is None and evidence["ability"] is not None:
            context.adapter_notes.append({"slot": slot, "side": role, "field": "ability",
                                          "source": "visible reveal event", "reason": "native parser omitted observed ability"})
            ability = evidence["ability"]
        if "ability" in evidence and ability != evidence["ability"]:
            raise ValueError(f"native opponent ability differs from visible evidence: {species}: {ability!r} vs {evidence['ability']!r}")
        if "tera" in evidence and (not tera or tera_type != evidence["tera"]):
            raise ValueError("native opponent Tera differs from visible evidence")
    transients = context.singleturn_effects.get((role, slot), set())
    if set(volatiles) & SINGLE_TURN != transients:
        context.adapter_notes.append({"slot": slot, "side": role, "field": "singleturn_volatiles",
                                      "source": "visible -singleturn/upkeep events",
                                      "reason": "native parser uses different transient storage/expiry"})
    persistent = context.persistent_effects.get((role, slot), set())
    for effect in persistent:
        if not any(v.startswith(effect) for v in volatiles):
            raise ValueError("native parser omitted a publicly started volatile")
    unproven = set(volatiles) - SINGLE_TURN - {v for v in volatiles if any(v.startswith(e) for e in persistent)}
    if unproven:
        context.adapter_notes.append({"slot": slot, "side": role, "field": "volatiles",
                                      "source": "visible -start/-end events",
                                      "reason": "native unproven/inferred effects excluded"})
    volatiles = sorted(persistent | transients)
    return {"slot": slot, "preview_species_id": preview, "species_id": species,
            "level": level, "active": is_active, "fainted": fainted,
            "hp_observation": health, "hp_observed_turn": observed_turn,
            "hp_current_interval": health if own or is_active or fainted else None,
            "current_hp": health["numerator"] if own else None,
            "max_hp": context.own_maxhp.get(slot) if own else None,
            "exact_stats": stats, "status": (status or "none") if observed and not fainted else None,
            "sleep_turns_elapsed": None, "toxic_counter": None, "protect_counter": None,
            "nature": None, "evs": None, "ivs": None,
            "boosts": boosts, "volatiles": volatiles, "base_types": base_types,
            "encore": context.encores.get((role, slot)),
            "types": effective_types, "terastallized": bool(tera),
            "tera_type": tera_type if own or "tera" in evidence else None,
            "moves": moves, "item": knowledge(item, observed=own or "item" in evidence),
            "ability": knowledge(ability, observed=own or "ability" in evidence),
            "removed_item": evidence.get("removed_item")}


def snapshot_from_framework(framework, battle, context):
    if context.payload is None or context.perspective is None:
        raise ValueError("no request-bound snapshot yet")
    if any(len(context.preview[r]) != 6 for r in ("p1", "p2")):
        raise ValueError("requires two complete six-member previews")
    if context.unsupported:
        raise ValueError(f"unsupported transcript mechanics: {sorted(context.unsupported)}")
    context.adapter_notes = []
    request = context.request
    native_request = battle.request_json if framework == "foulplay" else battle._last_request
    if canonical_json(native_request) != canonical_json(request):
        raise ValueError("native parser request is stale or differs from exact current request")
    legality = legal_actions_from_request(context.payload, context.request_slots, finished=context.finished)
    opponent = "p2" if context.perspective == "p1" else "p1"
    if framework == "foulplay":
        # Upstream applies request truth to a decision-time clone, not the protocol tracker.
        battle = deepcopy(battle)
        if not request.get("teamPreview") and not context.finished:
            battle.user.update_from_request_json(request)
    teams = {}
    for role in (context.perspective, opponent):
        members, active = _native_pokemon(framework, battle, role, context)
        own = {slot: p for slot, p in zip(context.request_slots, request["side"]["pokemon"], strict=True)} if role == context.perspective else {}
        records = [_project_member(framework, members.get(slot), slot, role, active, context, own.get(slot)) for slot in range(6)]
        active_slots = [p["slot"] for p in records if p["active"]]
        if len(active_slots) > 1:
            raise ValueError("singles native parser exposes multiple active members")
        teams[role] = {"active_slot": active_slots[0] if active_slots else None, "team": records}
    if framework == "foulplay":
        weather = str(battle.weather) if battle.weather and str(battle.weather) != "none" else None
        fields = {str(battle.field)} if battle.field else set()
        fields |= {f for f, enabled in (("trickroom", battle.trick_room), ("gravity", battle.gravity)) if enabled}
        native_conditions = {context.perspective: battle.user.side_conditions, opponent: battle.opponent.side_conditions}
        turn = int(battle.turn)
    else:
        weather_ids = [named(w) for w in battle.weather]
        if len(weather_ids) > 1:
            raise ValueError("multiple native weathers")
        weather = weather_ids[0] if weather_ids else None
        fields = {named(f) for f in battle.fields}
        native_conditions = {context.perspective: {named(c): v for c, v in battle.side_conditions.items()},
                             opponent: {named(c): v for c, v in battle.opponent_side_conditions.items()}}
        turn = battle.turn
    if turn != context.turn:
        raise ValueError("native parser turn differs from received transcript")
    if weather != context.observed_weather or fields != set(context.field_started):
        raise ValueError("native weather/field differs from visible event state")
    side_conditions = {}
    for role in (context.perspective, opponent):
        side_conditions[role] = {}
        for condition, layers in context.side_conditions[role].items():
            value = native_conditions[role].get(condition, 0)
            # Metamon stores start turns for nonstacking conditions, not layer counts.
            if (condition not in native_conditions[role] or
                    (framework == "foulplay" and value <= 0) or
                    (condition in STACKING and value != layers)):
                raise ValueError("native side condition disagrees with observed presence/layers")
            side_conditions[role][condition] = {"layers": layers, "started_turn": context.side_started[role][condition],
                                                "remaining_turns": None}
    terrain = sorted(fields & TERRAINS)
    if len(terrain) > 1:
        raise ValueError("multiple native terrains")
    public = {"payload_version": 2, "format": context.format_id,
              "rules": {"revision": context.rules_revision, "observed": context.rules},
              "self": teams[context.perspective], "opponent": teams[opponent],
              "field": {"weather": weather, "weather_started_turn": context.weather_started,
                        "weather_remaining_turns": None, "terrain": terrain[0] if terrain else None,
                        "rooms": sorted(fields & ROOMS), "pseudo_weather": sorted(fields - TERRAINS - ROOMS),
                        "field_started_turns": context.field_started,
                        "self_wish": context.wishes.get(context.perspective), "opponent_wish": context.wishes.get(opponent),
                        "self_future_sight": context.future_moves.get(context.perspective),
                        "opponent_future_sight": context.future_moves.get(opponent),
                        "self_side_conditions": side_conditions[context.perspective],
                        "opponent_side_conditions": side_conditions[opponent]},
              "history_summary": {"move_events": context.move_events, "damage_events": context.damage_events,
                                  "reveal_events": context.reveal_events,
                                  "order_semantics": "observed execution order, not inferred speed inequalities"},
              "request": {"rqid": legality.rqid, "wait": bool(request.get("wait")),
                          "teamPreview": bool(request.get("teamPreview")),
                          "forceSwitch": bool(request.get("forceSwitch", [False])[0]),
                          "trapped": bool(request.get("active", [{}])[0].get("trapped")),
                          "maybeTrapped": bool(request.get("active", [{}])[0].get("maybeTrapped"))}}
    return BattleSnapshot(adapter_version=f"{framework}-state-v2", battle_tag=context.battle_tag,
                          perspective=context.perspective, request_hash=hash_protocol_payload(context.payload),
                          history_hash=hash_history(context.lines), rqid=legality.rqid, turn=turn,
                          phase=legality.phase,
                          self_team=tuple(TeamSlot(i, normalized(s.split(",", 1)[0])) for i, s in enumerate(context.preview[context.perspective])),
                          opponent_team=tuple(TeamSlot(i, normalized(s.split(",", 1)[0])) for i, s in enumerate(context.preview[opponent])),
                          self_active_slot=teams[context.perspective]["active_slot"],
                          opponent_active_slot=teams[opponent]["active_slot"], legal_actions=legality.actions,
                          public_state_json=canonical_json(public))
