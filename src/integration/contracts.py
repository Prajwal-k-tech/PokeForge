"""Immutable identifiers shared by Showdown, FoulPlay, and Metamon adapters."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, Iterable


SCHEMA_VERSION = 1
_ID_PATTERN = re.compile(r"^[a-z0-9]+$")
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class ActionKind(StrEnum):
    MOVE = "move"
    SWITCH = "switch"
    TEAM_PREVIEW = "team_preview"
    STRUGGLE = "struggle"
    PASS = "pass"


class BattlePhase(StrEnum):
    TEAM_PREVIEW = "team_preview"
    TURN = "turn"
    FORCED_SWITCH = "forced_switch"
    WAIT = "wait"
    FINISHED = "finished"


def _require_id(value: str, field: str) -> None:
    if not _ID_PATTERN.fullmatch(value):
        raise ValueError(f"{field} must be a normalized Showdown ID, got {value!r}")


def canonical_json(value: Any) -> str:
    """Return the one JSON representation used for hashes and immutable payloads."""
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def hash_protocol_payload(payload: str | bytes) -> str:
    """Hash exact protocol bytes; callers must not parse/re-serialize first."""
    data = payload.encode("utf-8") if isinstance(payload, str) else payload
    return hashlib.sha256(data).hexdigest()


def hash_history(lines: Iterable[str]) -> str:
    """Hash visible protocol lines with length prefixes to preserve boundaries."""
    digest = hashlib.sha256()
    for line in lines:
        encoded = line.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True, order=True)
class TeamSlot:
    """Stable team-preview slot; availability never changes its identity."""

    slot: int
    species_id: str

    def __post_init__(self) -> None:
        if not 0 <= self.slot < 6:
            raise ValueError(f"team slot must be in 0..5, got {self.slot}")
        _require_id(self.species_id, "species_id")


@dataclass(frozen=True, slots=True, order=True)
class ActionKey:
    """Semantic action independent of every framework's integer numbering."""

    kind: ActionKind
    team_slot: int | None = None
    move_slot: int | None = None
    move_id: str | None = None
    tera: bool = False
    preview_order: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if self.kind is ActionKind.MOVE:
            if self.move_slot is None or not 0 <= self.move_slot < 4:
                raise ValueError("move actions require move_slot in 0..3")
            if self.move_id is None:
                raise ValueError("move actions require move_id")
            _require_id(self.move_id, "move_id")
            if self.team_slot is not None or self.preview_order:
                raise ValueError("move actions cannot contain switch/preview fields")
        elif self.kind is ActionKind.SWITCH:
            if self.team_slot is None or not 0 <= self.team_slot < 6:
                raise ValueError("switch actions require stable team_slot in 0..5")
            if self.move_slot is not None or self.move_id is not None:
                raise ValueError("switch actions cannot contain move fields")
            if self.tera or self.preview_order:
                raise ValueError("switch actions cannot tera or contain preview order")
        elif self.kind is ActionKind.TEAM_PREVIEW:
            if tuple(sorted(self.preview_order)) != tuple(range(6)):
                raise ValueError("Gen 9 OU Team Preview requires a permutation of slots 0..5")
            if any(
                value is not None
                for value in (self.team_slot, self.move_slot, self.move_id)
            ) or self.tera:
                raise ValueError("Team Preview actions only contain preview_order")
        else:
            if any(
                value is not None
                for value in (self.team_slot, self.move_slot, self.move_id)
            ) or self.tera or self.preview_order:
                raise ValueError(f"{self.kind} actions cannot contain action fields")

    @classmethod
    def move(cls, move_slot: int, move_id: str, *, tera: bool = False) -> ActionKey:
        return cls(ActionKind.MOVE, move_slot=move_slot, move_id=move_id, tera=tera)

    @classmethod
    def switch(cls, team_slot: int) -> ActionKey:
        return cls(ActionKind.SWITCH, team_slot=team_slot)

    @classmethod
    def team_preview(cls, order: Iterable[int]) -> ActionKey:
        return cls(ActionKind.TEAM_PREVIEW, preview_order=tuple(order))


@dataclass(frozen=True, slots=True)
class BattleSnapshot:
    """Hash-keyed immutable envelope produced independently by each adapter."""

    adapter_version: str
    battle_tag: str
    perspective: str
    request_hash: str
    history_hash: str
    rqid: int | None
    turn: int
    phase: BattlePhase
    self_team: tuple[TeamSlot, ...]
    opponent_team: tuple[TeamSlot, ...]
    self_active_slot: int | None
    opponent_active_slot: int | None
    legal_actions: tuple[ActionKey, ...]
    public_state_json: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version {self.schema_version}")
        if not self.adapter_version or not self.battle_tag:
            raise ValueError("adapter_version and battle_tag are required")
        if self.perspective not in {"p1", "p2"}:
            raise ValueError("perspective must be p1 or p2")
        for name, value in (
            ("request_hash", self.request_hash),
            ("history_hash", self.history_hash),
        ):
            if not _HASH_PATTERN.fullmatch(value):
                raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")
        if self.rqid is not None and self.rqid < 0:
            raise ValueError("rqid cannot be negative")
        if self.turn < 0:
            raise ValueError("turn cannot be negative")
        self._validate_team(self.self_team, "self_team")
        self._validate_team(self.opponent_team, "opponent_team")
        for active in (self.self_active_slot, self.opponent_active_slot):
            if active is not None and not 0 <= active < 6:
                raise ValueError("active slots must be in 0..5")
        if len(set(self.legal_actions)) != len(self.legal_actions):
            raise ValueError("legal_actions cannot contain duplicates")
        self._validate_phase_actions()
        if canonical_json(json.loads(self.public_state_json)) != self.public_state_json:
            raise ValueError("public_state_json must already use canonical_json")

    @staticmethod
    def _validate_team(team: tuple[TeamSlot, ...], field: str) -> None:
        slots = [member.slot for member in team]
        if len(slots) > 6 or len(slots) != len(set(slots)):
            raise ValueError(f"{field} must contain at most six unique stable slots")

    def _validate_phase_actions(self) -> None:
        kinds = {action.kind for action in self.legal_actions}
        allowed = {
            BattlePhase.TEAM_PREVIEW: {ActionKind.TEAM_PREVIEW},
            BattlePhase.TURN: {ActionKind.MOVE, ActionKind.SWITCH, ActionKind.STRUGGLE},
            BattlePhase.FORCED_SWITCH: {ActionKind.SWITCH},
            BattlePhase.WAIT: set(),
            BattlePhase.FINISHED: set(),
        }[self.phase]
        if not kinds <= allowed:
            raise ValueError(f"actions {kinds - allowed} are invalid during {self.phase}")
        if self.phase in {BattlePhase.WAIT, BattlePhase.FINISHED} and self.legal_actions:
            raise ValueError(f"{self.phase} snapshots cannot have legal actions")
        if self.phase not in {BattlePhase.WAIT, BattlePhase.FINISHED} and not self.legal_actions:
            raise ValueError(f"{self.phase} snapshots require at least one legal action")

    @property
    def snapshot_hash(self) -> str:
        return hash_protocol_payload(canonical_json(asdict(self)))

    @property
    def semantic_hash(self) -> str:
        """Compare independent adapters without conflating state with adapter provenance."""
        state = asdict(self)
        state.pop("adapter_version")
        state["legal_actions"] = sorted(state["legal_actions"], key=canonical_json)
        state["self_team"] = sorted(state["self_team"], key=lambda member: member["slot"])
        state["opponent_team"] = sorted(state["opponent_team"], key=lambda member: member["slot"])
        return hash_protocol_payload(canonical_json(state))
