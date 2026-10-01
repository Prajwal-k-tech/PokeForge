"""Translate pinned framework action encodings into canonical semantic actions.

These adapters intentionally consume a raw Showdown request plus an externally maintained stable
team-slot map. Neither FoulPlay's wire choices nor Metamon's policy indices are safe identifiers.
"""

from __future__ import annotations

import json
import operator

from .contracts import ActionKey, ActionKind, BattlePhase
from .showdown_request import legal_actions_from_request


def _metamon_move_sort_key(name: str) -> str:
    """Pinned Metamon's `move_name`: lowercase alphabetic characters only."""
    return "".join(character for character in name if character.isalpha()).lower()


def _metamon_species_sort_key(name: str) -> str:
    """Pinned Metamon's `pokemon_name`: lowercase alphanumeric characters."""
    return "".join(character for character in name if character.isalnum()).lower()


def _request(request_payload: str) -> dict:
    payload = json.loads(request_payload)
    if not isinstance(payload, dict):
        raise ValueError("Showdown request must be a JSON object")
    return payload


def foulplay_wire_choice_to_action_key(
    wire_choice: str, request_payload: str, request_order_slots: tuple[int, ...]
) -> ActionKey:
    """Map pinned FoulPlay's `/choose` wire command to an action in this request.

    FoulPlay sends a switch's *current request-list position* (one-based), not a stable full-team
    slot. Moves are named, so we resolve the exact currently legal move rather than trusting a
    framework-local move index.
    """
    legal = legal_actions_from_request(request_payload, request_order_slots)
    # FoulPlay hands its formatter a command and rqid separately, while a captured outbound
    # protocol line joins them with `|`; accept both representations.
    command, separator, rqid = wire_choice.strip().lower().partition("|")
    if separator and (not rqid.isdigit() or int(rqid) != legal.rqid):
        raise ValueError("FoulPlay command has a stale or malformed request ID")
    tokens = command.split()
    if tokens[:2] == ["/choose", "move"]:
        if len(tokens) not in (3, 4) or (len(tokens) == 4 and tokens[3] != "terastallize"):
            raise ValueError(f"unsupported FoulPlay move command: {wire_choice!r}")
        move_id = tokens[2]
        tera = "terastallize" in tokens[3:]
        if move_id == "struggle":
            matches = [
                action
                for action in legal.actions
                if action.kind is ActionKind.STRUGGLE and not tera
            ]
        else:
            matches = [
                action
                for action in legal.actions
                if action.kind is ActionKind.MOVE
                and action.move_id == move_id
                and action.tera is tera
            ]
    elif tokens[:1] == ["/switch"] or tokens[:2] == ["/choose", "switch"]:
        expected_length = 2 if tokens[:1] == ["/switch"] else 3
        if len(tokens) != expected_length or not tokens[-1].isdigit():
            raise ValueError(f"unsupported FoulPlay switch command: {wire_choice!r}")
        request_position = int(tokens[-1]) - 1
        if not 0 <= request_position < len(request_order_slots):
            raise ValueError(f"FoulPlay switch position is out of range: {wire_choice!r}")
        stable_slot = request_order_slots[request_position]
        matches = [
            action
            for action in legal.actions
            if action.kind is ActionKind.SWITCH and action.team_slot == stable_slot
        ]
    else:
        raise ValueError(f"unsupported FoulPlay command: {wire_choice!r}")
    if len(matches) != 1:
        raise ValueError(f"FoulPlay command is not exactly one legal action: {wire_choice!r}")
    return matches[0]


def metamon_action_index_to_action_key(
    action_index: int, request_payload: str, request_order_slots: tuple[int, ...]
) -> ActionKey:
    """Map Metamon DefaultActionSpace's 13-way index to an action in this request.

    Pinned Metamon uses the alphabetically sorted full moveset at 0..3 (disabled moves keep their
    indices), alphabetically sorted living bench Pokémon at 4..8, and Tera moves at 9..12.
    Move indices 0..3 alias Struggle, while legal switches remain available. Team Preview
    is handled by a separate Metamon component and is intentionally not represented here.
    """
    legal = legal_actions_from_request(request_payload, request_order_slots)
    if legal.phase is not BattlePhase.TURN and legal.phase is not BattlePhase.FORCED_SWITCH:
        raise ValueError(f"Metamon DefaultActionSpace has no mapping for {legal.phase}")
    try:
        action_index = operator.index(action_index)
    except TypeError as error:
        raise ValueError("Metamon action index must be an integer") from error
    if action_index < 0 or action_index > 12:
        raise ValueError(f"Metamon action index must be in 0..12, got {action_index}")

    struggle = [action for action in legal.actions if action.kind is ActionKind.STRUGGLE]
    if struggle and 0 <= action_index <= 3:
        return struggle[0]

    request = _request(request_payload)
    move_options = sorted(
        enumerate(request.get("active", [{}])[0].get("moves", [])),
        key=lambda pair: _metamon_move_sort_key(pair[1]["id"]),
    )
    switch_by_slot = {
        action.team_slot: action
        for action in legal.actions
        if action.kind is ActionKind.SWITCH
    }
    members = request.get("side", {}).get("pokemon", [])
    sorted_switches = sorted(
        (
            (member, request_order_slots[position])
            for position, member in enumerate(members)
            if not member.get("active", False)
            and not member.get("condition", "").endswith(" fnt")
        ),
        key=lambda pair: _metamon_species_sort_key(
            pair[0].get("details", "").split(",", 1)[0]
        ),
    )

    if 4 <= action_index <= 8:
        switch_position = action_index - 4
        if switch_position < len(sorted_switches):
            action = switch_by_slot.get(sorted_switches[switch_position][1])
            if action is not None:
                return action
    else:
        wants_tera = action_index >= 9
        move_position = action_index - 9 if wants_tera else action_index
        if move_position < len(move_options) and not struggle:
            move_slot, move = move_options[move_position]
            action = ActionKey.move(move_slot, move["id"], tera=wants_tera)
            if action in legal.actions:
                return action
    raise ValueError(f"Metamon action index is illegal in this request: {action_index}")
