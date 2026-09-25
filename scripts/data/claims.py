"""What a taxonomic opinion actually asserts, and how strongly.

An ingested opinion row already has the shape of a claim: a subject name, a
relation (``status``), a target (``related_taxon``), a basis and a source. What
the row does not say by itself is what kind of scientific statement it is and
how much weight it can bear. This module derives those, deterministically and
without ever making an opinion stronger than its source:

    assertion  what the paper did with the name (used it, classified it as
               valid, synonymized it, ...)
    strength   how the claim was made: usage < implied < stated < argued
    authority  who recorded it: a PBDB compiler, a direct reading of the paper,
               or a rule in this build

Only ``stated`` and ``argued`` claims can move a hypothesis's derived state;
only ``argued`` ones can sink or revive it. ``usage`` (a paper merely reporting
fossils under a name) never argues for or against anything.
"""
from __future__ import annotations

from typing import Any

CLAIM_RULES_VERSION = "claim-semantics/v1"

# status -> assertion
ASSERTIONS = {
    "identified_as": "uses_name",
    "belongs_to": "classifies_as_valid",
    "subjective_synonym_of": "synonymizes",
    "objective_synonym_of": "synonymizes",
    "nomen_dubium": "declares_nomen_status",
    "nomen_nudum": "declares_nomen_status",
    "nomen_vanum": "declares_nomen_status",
    "nomen_oblitum": "declares_nomen_status",
    "replaced_by": "nomenclatural_correction",
    "misspelling_of": "nomenclatural_correction",
    "invalid_subgroup_of": "invalid_subgroup",
    "sister_to": "phylogenetic_placement",
}

STRENGTHS = ("usage", "implied", "stated", "argued")
STRENGTH_RANK = {name: rank for rank, name in enumerate(STRENGTHS)}
# PBDB's own basis vocabulary, which direct extraction also uses.
BASIS_STRENGTH = {
    "implied": "implied",
    "stated without evidence": "stated",
    "stated with evidence": "argued",
}
# A claim at or above this strength can move a derived state; at "argued" it
# can sink or revive a hypothesis.
MOVES_STATE = "stated"
DECISIVE = "argued"

AUTHORITIES = {
    "pbdb_opinion": "pbdb_compiled",
    "full_text": "direct_full_text",
    "abstract": "direct_abstract_unverified",
    "derived_from_occurrence": "build_derived",
}
DERIVED_RULE = "identified-as-from-occurrence/v2"


def strength_of(opinion: dict[str, Any]) -> str:
    """How strongly the opinion was made, never stronger than its source says.

    Name usage derived from fossil identifications is always ``usage``. A
    recorded basis maps to implied/stated/argued. A direct reading with no
    recorded basis counts as ``stated``, not as evidence-backed.
    """
    if opinion["status"] == "identified_as" or opinion["source"] == "derived_from_occurrence":
        return "usage"
    basis = (opinion.get("basis") or "").strip().casefold()
    if basis in BASIS_STRENGTH:
        return BASIS_STRENGTH[basis]
    return "stated" if opinion["source"] in {"full_text", "abstract"} else "implied"


def genus_of(name: str | None) -> str | None:
    words = (name or "").split()
    return words[0] if len(words) >= 2 and words[1][:1].islower() else None


def assertion_of(opinion: dict[str, Any]) -> str:
    """The kind of statement. A species placed in a genus other than the one in
    its tracked (normalized) name is kept as a species, but in another genus:
    "Gorgosaurus lancensis" is not a claim that Nanotyrannus is valid."""
    status = opinion["status"]
    if status == "belongs_to":
        genus = genus_of(opinion.get("taxon"))
        parent = (opinion.get("related_taxon") or "").strip()
        if genus and parent and " " not in parent and parent != genus:
            return "places_in_other_genus"
    return ASSERTIONS[status]


def source_records(opinion: dict[str, Any]) -> list[str]:
    """Identifiers of the upstream records this claim was taken from."""
    if opinion.get("source_records"):
        return list(opinion["source_records"])
    if opinion["id"].startswith("pbdb-opinion:"):
        return [opinion["id"]]
    return []


def classify(opinion: dict[str, Any]) -> dict[str, Any]:
    """The claim fields added to an opinion row. Pure and deterministic."""
    derived = opinion["source"] == "derived_from_occurrence"
    return {
        "name_as_published": opinion.get("published_as") or opinion["taxon"],
        "assertion": assertion_of(opinion),
        "strength": strength_of(opinion),
        "authority": AUTHORITIES[opinion["source"]],
        "derivation_rule": DERIVED_RULE if derived else None,
        "source_records": source_records(opinion),
    }


def at_least(strength: str, floor: str) -> bool:
    return STRENGTH_RANK[strength] >= STRENGTH_RANK[floor]
