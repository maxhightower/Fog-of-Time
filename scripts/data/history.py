"""Replay a creature's claims into turning points and corpus-relative states.

Two things are derived, and both are views over the claim ledger, never
scientific authority:

Turning points (``key_events``)
    The moments that change a hypothesis's life. Curated creatures list them by
    hand; official creatures follow ``automatic_key_events``.

States (``derive_states``)
    What the ingested literature, read in publication order, looked like at
    each moment. The vocabulary describes the corpus, not the animal:

    in_use     the latest turning point treats the name as valid (or merely
               records its use) and no stated claim has disputed it since
    contested  a challenge is open, or a stated claim has disputed the latest
               turning point (a sunk name still defended, a defended name
               still sunk)
    sunk       the latest turning point is an evidence-backed claim sinking the
               name, and no stated claim has defended it since

Nothing here counts papers to decide what is true. "Sunk" says what the most
recent argued claim in the corpus did; it does not say the animal is not real.
Every state change keeps the claim or turning point that caused it.
"""
from __future__ import annotations

from typing import Any

from claims import DECISIVE, MOVES_STATE, at_least

TURNING_POINT_RULES_VERSION = "automatic-turning-points/v2"
STATE_RULES_VERSION = "corpus-state/v1"

# The side of the argument a turning point's claim must be on.
STANCE_SIDES = {
    "proposes": "for", "supports": "for", "revives": "for",
    "recorded": "usage",
    "challenges": "against", "refutes": "against",
}
STATE_AFTER = {
    "proposes": "in_use", "recorded": "in_use", "supports": "in_use", "revives": "in_use",
    "challenges": "contested", "refutes": "sunk",
}
# Minimum claim strength each turning point needs. A curated turning point
# resting on a weaker claim must say why, in a ``rationale``.
STANCE_FLOOR = {
    "proposes": "implied", "recorded": "usage",
    "supports": MOVES_STATE, "challenges": MOVES_STATE,
    "refutes": DECISIVE, "revives": DECISIVE,
}
# Stated (not merely implied) papers that keep treating a challenged name as
# valid before the challenge counts as answered.
CONSENSUS = 3


def automatic_key_events(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The written-down rule for official creatures.

    ``claims`` are in publication order and carry ``side`` (for, against,
    neutral, usage) and ``strength``.

    - Born with the first claim treating the name as valid (``proposes``) or,
      if a paper only reports fossils under it, ``recorded``.
    - A stated claim sinking an in-use name challenges it; an argued one sinks it.
    - A challenge is answered by an argued defence, or by three stated ones; an
      argued sinking claim during a challenge sinks it.
    - A sunk name comes back only with an argued defence.
    - Usage, implied claims and neutral claims are evidence without being
      turning points.
    """
    events: list[dict[str, Any]] = []
    state: str | None = None
    defences = 0
    for claim in claims:
        side, strength = claim["side"], claim["strength"]
        stance = None
        if state is None:
            if side == "for":
                stance = "proposes"
            elif side == "usage":
                stance = "recorded"
        elif side == "for" and at_least(strength, MOVES_STATE):
            if state == "contested":
                defences += 1
                if at_least(strength, DECISIVE) or defences >= CONSENSUS:
                    stance = "supports"
            elif state == "sunk" and at_least(strength, DECISIVE):
                stance = "revives"
        elif side == "against" and at_least(strength, MOVES_STATE):
            if state in {"in_use", "contested"} and at_least(strength, DECISIVE):
                stance = "refutes"
            elif state == "in_use":
                stance = "challenges"
        if stance is None:
            continue
        events.append({"publication_id": claim["publication_id"], "stance": stance, "opinion_id": claim["id"]})
        state = STATE_AFTER[stance]
        defences = 0
    return events


def derive_states(key_events: list[dict[str, Any]], claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every change of corpus state, in publication order, with its cause.

    ``key_events`` carry the ``opinion_id`` they rest on; ``claims`` are every
    claim on the creature's names in publication order (``id``, ``year``,
    ``publication_id``, ``side``, ``strength``). A turning point sets the base
    state. Between turning points, a stated claim on the opposite side of the
    base marks the hypothesis contested until the next turning point.

    Each state depends only on claims published at or before it, so replaying
    to any year never uses later literature.
    """
    position = {claim["id"]: index for index, claim in enumerate(claims)}
    events_at: dict[int, list[dict[str, Any]]] = {}
    event_opinions = {event["opinion_id"] for event in key_events}
    last = -1
    for order, event in enumerate(key_events):
        # Curated turning points in one year may be listed in a different
        # order from the claim stream; never let one move before its predecessor.
        at = max(position[event["opinion_id"]], last)
        events_at.setdefault(at, []).append({**event, "event_order": order})
        last = at

    changes: list[dict[str, Any]] = []
    base: str | None = None
    state: str | None = None
    for index, claim in enumerate(claims):
        cause = None
        if base is not None and claim["id"] not in event_opinions and at_least(claim["strength"], MOVES_STATE):
            opposes = (base == "in_use" and claim["side"] == "against") or (base == "sunk" and claim["side"] == "for")
            if opposes and state != "contested":
                state = "contested"
                cause = {"kind": "opposing_claim", "opinion_id": claim["id"], "publication_id": claim["publication_id"], "stance": None}
        for event in events_at.get(index, []):
            base = state = STATE_AFTER[event["stance"]]
            cause = {"kind": "turning_point", "opinion_id": event["opinion_id"], "publication_id": event["publication_id"],
                     "stance": event["stance"], "event_order": event["event_order"]}
        if cause is None:
            continue
        year = claim["year"]
        if cause["kind"] == "turning_point":
            year = max(year, claims[position[cause["opinion_id"]]]["year"])
        changes.append({"year": year, "state": state, **cause})
    return changes


def state_at(changes: list[dict[str, Any]], year: int) -> dict[str, Any] | None:
    """The last state change published in or before ``year``."""
    current = None
    for change in changes:
        if change["year"] > year:
            break
        current = change
    return current
