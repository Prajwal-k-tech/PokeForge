"""Authoritative semantic legal actions from one raw Showdown singles request."""

from __future__ import annotations

import itertools
import json
from dataclasses import dataclass

from .contracts import ActionKey, ActionKind, BattlePhase


@dataclass(frozen=True, slots=True)
class RequestActions:
    phase: BattlePhase
    rqid: int | None
    actions: tuple[ActionKey, ...]


def _switches(request: dict, request_order_slots: tuple[int, ...]) -> tuple[ActionKey, ...]:
    pokemon = request.get("side", {}).get("pokemon", [])
    if len(pokemon) != len(request_order_slots):
        raise ValueError("request_order_slots must align with request side.pokemon")
    actions = []
    for member, stable_slot in zip(pokemon, request_order_slots, strict=True):
        condition = member.get("condition", "")
        if not member.get("active", False) and not condition.endswith(" fnt"):
            actions.append(ActionKey.switch(stable_slot))
    return tuple(actions)


def legal_actions_from_request(
    request_payload: str,
    request_order_slots: tuple[int, ...],
    *,
    finished: bool = False,
) -> RequestActions:
    """Translate raw Gen 9 singles request legality without compacting stable slots."""
    request = json.loads(request_payload)
    rqid = request.get("rqid")
    if finished:
        return RequestActions(BattlePhase.FINISHED, rqid, ())
    if request.get("wait", False):
        return RequestActions(BattlePhase.WAIT, rqid, ())
    if request.get("teamPreview", False):
        if len(request_order_slots) != 6 or set(request_order_slots) != set(range(6)):
            raise ValueError("Gen 9 OU Team Preview requires stable slots 0..5")
        actions = tuple(
            ActionKey.team_preview(order)
            for order in itertools.permutations(request_order_slots)
        )
        return RequestActions(BattlePhase.TEAM_PREVIEW, rqid, actions)

    force_switch = request.get("forceSwitch", [False])
    if force_switch and force_switch[0]:
        return RequestActions(
            BattlePhase.FORCED_SWITCH,
            rqid,
            _switches(request, request_order_slots),
        )

    active = request.get("active")
    if not active or len(active) != 1:
        raise ValueError("expected one active request entry for a singles turn")
    active_request = active[0]
    actions = []
    for move_slot, move in enumerate(active_request.get("moves", [])):
        if move_slot >= 4 or move.get("disabled", False) or move.get("pp", 0) <= 0:
            continue
        move_id = move.get("id")
        if move_id == "struggle":
            actions.append(ActionKey(ActionKind.STRUGGLE))
            continue
        actions.append(ActionKey.move(move_slot, move_id))
        if active_request.get("canTerastallize"):
            actions.append(ActionKey.move(move_slot, move_id, tera=True))
    if not active_request.get("trapped", False):
        actions.extend(_switches(request, request_order_slots))
    if not actions:
        raise ValueError("request produced no explicit legal action")
    return RequestActions(BattlePhase.TURN, rqid, tuple(actions))
