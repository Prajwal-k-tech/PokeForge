"""Exact-request legality gate; independent of Torch and checkpoint architecture."""

from __future__ import annotations

import json
import math
import operator
from dataclasses import dataclass

from .contracts import ActionKey, ActionKind, BattlePhase, canonical_json, hash_protocol_payload
from .framework_actions import metamon_action_index_to_action_key
from .showdown_request import legal_actions_from_request


@dataclass(frozen=True, slots=True)
class PolicyRequest:
    battle_tag: str
    payload: str
    request_hash: str
    rqid: int
    slots: tuple[int, ...]
    indices: tuple[ActionKey | None, ...]

    @property
    def legal_mask(self) -> tuple[bool, ...]:
        return tuple(action is not None for action in self.indices)

    def wire_choice(self, index: int) -> str:
        try:
            index = operator.index(index)
        except TypeError as error:
            raise ValueError("policy action must be an integer index") from error
        if not 0 <= index < 13 or self.indices[index] is None:
            raise ValueError("policy selected an illegal index")
        action = self.indices[index]
        if action.kind is ActionKind.SWITCH:
            choice = f"/choose switch {self.slots.index(action.team_slot) + 1}"
        elif action.kind is ActionKind.STRUGGLE:
            choice = "/choose move struggle"
        else:
            choice = f"/choose move {action.move_id}" + (" terastallize" if action.tera else "")
        return f"{choice}|{self.rqid}"


class RequestPolicyGate:
    """One synchronous local policy stream; fail closed on stale/unsupported requests."""

    def __init__(self):
        self.preview_tag = None
        self.preview_idents = ()
        self.current: PolicyRequest | None = None
        self.latest_payload = None
        self.latest_tag = None

    def observe(self, battle_tag: str, payload: str) -> None:
        request = json.loads(payload)
        if (not isinstance(request, dict) or type(request.get("rqid")) is not int
                or request["rqid"] < 0):
            raise ValueError("expected a Showdown request with an integer rqid")
        members = request.get("side", {}).get("pokemon", [])
        idents = tuple(member["ident"] for member in members)
        if request.get("teamPreview"):
            if len(idents) != 6 or len(set(idents)) != 6:
                raise ValueError("six unique own preview identities are required")
            self.preview_tag, self.preview_idents = battle_tag, idents
        self.latest_payload, self.latest_tag = payload, battle_tag

    def activate(self, battle_tag: str, parsed_request: dict) -> PolicyRequest:
        payload = self.latest_payload
        if battle_tag != self.latest_tag or payload is None or json.loads(payload) != parsed_request:
            raise ValueError("parsed battle request differs from latest exact received request")
        if self.preview_tag != battle_tag:
            raise ValueError("missing own Team Preview slot map")
        request = json.loads(payload)
        members = request.get("side", {}).get("pokemon", [])
        idents = tuple(member["ident"] for member in members)
        if sorted(idents) != sorted(self.preview_idents):
            raise ValueError("own identities changed; no silent slot reassignment")
        if any(member.get("reviving") for member in members):
            raise ValueError("revival is not supported by this policy boundary")
        slots = tuple(self.preview_idents.index(ident) for ident in idents)
        legal = legal_actions_from_request(payload, slots)
        if legal.phase not in {BattlePhase.TURN, BattlePhase.FORCED_SWITCH}:
            raise ValueError(f"cannot run a policy during {legal.phase}")
        if any(action.move_id == "recharge" for action in legal.actions):
            raise ValueError("Recharge action aliases are not yet supported")
        indices = []
        for index in range(13):
            try:
                indices.append(metamon_action_index_to_action_key(index, payload, slots))
            except ValueError:
                indices.append(None)
        if set(action for action in indices if action is not None) != set(legal.actions):
            raise ValueError("policy indices do not cover the request's legal actions")
        self.current = PolicyRequest(battle_tag, payload, hash_protocol_payload(payload),
                                     request["rqid"], slots, tuple(indices))
        return self.current

    def validate(self, ticket: PolicyRequest, parsed_request: dict) -> None:
        if (ticket.battle_tag != self.latest_tag or self.latest_payload is None
                or ticket.request_hash != hash_protocol_payload(self.latest_payload)
                or json.loads(ticket.payload) != parsed_request):
            raise ValueError("stale policy request; refuse to send its action")


def restrict_probabilities(probabilities, ticket: PolicyRequest, current_request_hash: str):
    """Remove illegal mass after clipping, preserving relative legal probabilities."""
    if ticket.request_hash != current_request_hash:
        raise ValueError("stale probability/request hash")
    if len(probabilities) != 13 or any(not math.isfinite(p) or p < 0 for p in probabilities):
        raise ValueError("expected thirteen finite nonnegative policy probabilities")
    if not math.isclose(sum(probabilities), 1.0, rel_tol=1e-5, abs_tol=1e-6):
        raise ValueError("policy probabilities must sum to one")
    kept = [p if legal else 0.0 for p, legal in zip(probabilities, ticket.legal_mask, strict=True)]
    total = sum(kept)
    if total <= 0:
        raise ValueError("policy has no probability on legal choices")
    removed = sum(p for p, legal in zip(probabilities, ticket.legal_mask, strict=True) if not legal)
    return tuple(p / total for p in kept), removed
