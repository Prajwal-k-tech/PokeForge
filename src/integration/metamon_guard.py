"""Opt-in local Metamon inference guard; never edits the pinned upstream source/checkpoint."""

from __future__ import annotations

import json
from types import MethodType, SimpleNamespace

from .contracts import hash_protocol_payload
from .policy_gate import RequestPolicyGate, restrict_probabilities


def install_local_guard(log_stream):
    """Install in one isolated CLI process, for one synchronous Gen 9 OU policy stream."""
    import torch
    import numpy as np
    import metamon.env.wrappers as wrappers
    from amago.nets.policy_dists import _Categorical
    from metamon.env.metamon_player import PokeAgentPlayer

    gate = RequestPolicyGate()
    stats = {"choices": 0, "probability_masks": 0, "rejected_commands": 0,
             "server_errors": 0, "fallback_attempts": 0,
             "removed_mass_total": 0.0, "removed_mass_max": 0.0}
    pending = {"ticket": None}

    def record(event, **data):
        log_stream.write(json.dumps({"event": event, **data}, sort_keys=True) + "\n")
        log_stream.flush()

    class GuardedPlayer(PokeAgentPlayer):
        async def _handle_battle_message(self, split_messages):
            tag = split_messages[0][0].removeprefix(">")
            for line in split_messages[1:]:
                if len(line) > 2 and line[1] == "request" and line[2]:
                    # Splitting and rejoining separators preserves the exact JSON substring,
                    # including separators inside JSON strings. No parse/reserialize hash.
                    payload = "|".join(line[2:])
                    gate.observe(tag, payload)
                    record("request", battle_tag=tag, payload=payload,
                           request_hash=hash_protocol_payload(payload))
                elif len(line) > 1 and line[1] == "error":
                    stats["server_errors"] += 1
                    record("server_error", battle_tag=tag, message="|".join(line))
            return await super()._handle_battle_message(split_messages)

        async def _handle_battle_request(self, battle, maybe_default_order=False):
            if maybe_default_order:
                stats["fallback_attempts"] += 1
                record("fallback_rejected", battle_tag=battle.battle_tag)
                raise ValueError("unvalidated upstream default-choice fallback is disabled")
            return await super()._handle_battle_request(battle, maybe_default_order=False)

    original_embed = wrappers.PokeEnvWrapper.embed_battle

    def guarded_embed(env, battle):
        obs = original_embed(env, battle)
        if not battle.finished:
            ticket = gate.activate(battle.battle_tag, battle._last_request)
            record("activate", battle_tag=ticket.battle_tag, rqid=ticket.rqid,
                   request_hash=ticket.request_hash, legal_mask=ticket.legal_mask)
            obs["_pokeforge_request_hash"] = np.frombuffer(bytes.fromhex(ticket.request_hash), dtype=np.uint8).copy()
        else:
            gate.current = None
            pending["ticket"] = None
            obs["_pokeforge_request_hash"] = np.zeros(32, dtype=np.uint8)
        return obs

    def guarded_order(env, action, battle):
        ticket = pending["ticket"]
        try:
            if ticket is None:
                raise ValueError("no policy inference ticket")
            if battle.finished:
                raise ValueError("refuse an action after battle completion")
            gate.validate(ticket, battle._last_request)
            index = env.metamon_action_space.agent_output_to_action(
                state=env._most_recent_state, agent_output=action
            ).action_idx
            wire = ticket.wire_choice(index)
        except ValueError as error:
            stats["rejected_commands"] += 1
            env.invalid_action_counter += 1
            record("rejected_command", reason=str(error))
            raise
        stats["choices"] += 1
        env.valid_action_counter += 1
        record("choice", battle_tag=ticket.battle_tag, rqid=ticket.rqid,
               request_hash=ticket.request_hash, index=index, wire_command=wire)
        pending["ticket"] = None
        return SimpleNamespace(message=wire)

    wrappers.PokeAgentPlayer = GuardedPlayer
    wrappers.PokeEnvWrapper.embed_battle = guarded_embed
    wrappers.PokeEnvWrapper.action_to_move = guarded_order

    def attach_policy(policy):
        original_get_actions = policy.get_actions
        original_forward = policy.actor.forward

        def guarded_get_actions(*args, **kwargs):
            ticket = gate.current
            if ticket is None:
                raise ValueError("policy inference has no active exact request")
            gate.validate(ticket, json.loads(ticket.payload))
            obs = kwargs.get("obs", args[0] if args else None)
            if obs is None or "_pokeforge_request_hash" not in obs:
                raise ValueError("policy observation has no exact-request hash tag")
            tag = obs["_pokeforge_request_hash"]
            if tag.shape != (1, 1, 32) or bytes(tag[0, 0].cpu().tolist()).hex() != ticket.request_hash:
                raise ValueError("policy observation is from a stale request")
            # Metadata crosses the environment queue with this observation, then is stripped
            # before the unchanged encoder/checkpoint sees it.
            encoder_obs = {key: value for key, value in obs.items() if key != "_pokeforge_request_hash"}
            if "obs" in kwargs:
                kwargs = kwargs | {"obs": encoder_obs}
            else:
                args = (encoder_obs, *args[1:])
            pending["ticket"] = ticket
            result = original_get_actions(*args, **kwargs)
            gate.validate(ticket, json.loads(ticket.payload))
            return result

        def guarded_forward(actor, *args, **kwargs):
            dist = original_forward(*args, **kwargs)
            ticket = pending["ticket"]
            if ticket is None or dist.probs.shape[:2] != (1, 1) or dist.probs.shape[-1] != 13:
                raise ValueError("guard requires one synchronous 13-action inference stream")
            gate.validate(ticket, json.loads(ticket.payload))
            primary = dist.probs[0, 0, -1].detach().float().cpu().tolist()
            expected, removed = restrict_probabilities(primary, ticket, hash_protocol_payload(gate.latest_payload))
            mask = torch.tensor(ticket.legal_mask, dtype=torch.bool, device=dist.probs.device)
            safe = _Categorical(probs=dist.probs.masked_fill(~mask, 0.0))
            if not torch.allclose(safe.probs[0, 0, -1].float(),
                                  torch.tensor(expected, device=dist.probs.device), atol=1e-6):
                raise ValueError("tensor mask differs from reference probability gate")
            stats["probability_masks"] += 1
            stats["removed_mass_total"] += removed
            stats["removed_mass_max"] = max(stats["removed_mass_max"], removed)
            record("distribution", battle_tag=ticket.battle_tag, rqid=ticket.rqid,
                   request_hash=ticket.request_hash, raw_probabilities=primary,
                   legal_probabilities=expected, removed_illegal_mass=removed)
            return safe

        policy.actor.forward = MethodType(guarded_forward, policy.actor)
        policy.get_actions = guarded_get_actions

    return attach_policy, stats
