"""Framework-neutral integration contracts for competitive PokeForge."""

from .contracts import (
    ActionKey,
    ActionKind,
    BattlePhase,
    BattleSnapshot,
    TeamSlot,
    canonical_json,
    hash_history,
    hash_protocol_payload,
)
from .showdown_request import RequestActions, legal_actions_from_request

__all__ = [
    "ActionKey",
    "ActionKind",
    "BattlePhase",
    "BattleSnapshot",
    "TeamSlot",
    "canonical_json",
    "hash_history",
    "hash_protocol_payload",
    "RequestActions",
    "legal_actions_from_request",
]
from .framework_actions import (
    foulplay_wire_choice_to_action_key,
    metamon_action_index_to_action_key,
)

__all__ += [
    "foulplay_wire_choice_to_action_key",
    "metamon_action_index_to_action_key",
]
