#!/usr/bin/env python3
"""Build Fog of Time's local SQLite database and browser-ready static artifacts.

No network access is performed here. Checked-in paper extraction JSON is validated,
normalized into SQLite, and exported to static JSON for the Vite client.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
import sqlite3
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from claims import CLAIM_RULES_VERSION, DECISIVE, MOVES_STATE, at_least, classify  # noqa: E402
from history import (  # noqa: E402
    STANCE_FLOOR, STANCE_SIDES, STATE_RULES_VERSION, TURNING_POINT_RULES_VERSION, automatic_key_events, derive_states,
)
from publication_identity import IDENTITY_RULES_VERSION, audit as audit_identity, normalize_doi  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
EXTRACTED = ROOT / "data" / "extracted"
THEORETICAL = ROOT / "data" / "theoretical"
SQL_SCHEMA = ROOT / "db" / "schema.sql"
BUILD_DIR = ROOT / "build"
DB_PATH = BUILD_DIR / "fog-of-time.sqlite"
PUBLIC_DATA = ROOT / "public" / "data"
TIMELINE_PATH = PUBLIC_DATA / "timeline" / "all.json"
MANIFEST_PATH = PUBLIC_DATA / "manifest.json"
CREATURES_PATH = PUBLIC_DATA / "theoretical" / "creatures.json"
OPINION_IMPORT_MANIFEST = ROOT / "data" / "acquisition" / "pbdb-opinion-import-manifest.json"
REPORT_PATH = BUILD_DIR / "model-report.json"

SCHEMA_VERSION = "fog-of-time.paper-extraction/v1"
EVIDENCE_TYPES = {
    "body_fossil", "fossil_occurrence", "trace_fossil", "egg", "nest", "coprolite", "trackway",
    "skin_impression", "feather_impression", "soft_tissue", "bone_histology",
    "tooth", "gastrolith", "pathology", "bite_mark", "biomolecule",
}
EVIDENCE_ROLES = {
    "original_discovery", "original_description", "new_measurement", "new_imaging",
    "redescription", "reinterpretation", "secondary_citation", "review",
}
CREATURE_SCHEMA_VERSION = "fog-of-time.theoretical-creature/v3"
# A taxonomic opinion is one paper's verdict on a name. Most come from PBDB;
# "identified_as" is derived from a paper's own occurrence identifications and
# "sister_to" records a phylogenetic placement stated in a paper.
OPINION_STATUSES = {
    "belongs_to", "subjective_synonym_of", "objective_synonym_of", "replaced_by", "invalid_subgroup_of",
    "misspelling_of", "nomen_dubium", "nomen_nudum", "nomen_vanum", "nomen_oblitum", "sister_to", "identified_as",
}
OPINION_SOURCES = {"pbdb_opinion", "full_text", "abstract", "derived_from_occurrence"}
# Name usage is evidence that a name was used, never an argument about it, so
# no hypothesis rule may count it for or against.
USAGE_STATUSES = {"identified_as"}
REIDENTIFICATION = re.compile(r"original/identified name as (?P<identified>.+?) and the accepted name as (?P<accepted>.+?)\.$")
QUALIFIERS = re.compile(r"<[^>]*>|\b(?:n\. gen\.|n\. sp\.|cf\.|aff\.|sp\.|indet\.)|[?\"]")
AGE_PRECISIONS = {
    "explicit_range", "approximate_range", "reported_point", "approximate_point", "derived_interval", "unknown",
}


def fail(path: Path, message: str) -> None:
    raise ValueError(f"{path.relative_to(ROOT)}: {message}")


def required(mapping: dict[str, Any], keys: tuple[str, ...], path: Path, context: str) -> None:
    missing = [key for key in keys if key not in mapping]
    if missing:
        fail(path, f"{context} missing required keys: {', '.join(missing)}")


def validate_document(document: dict[str, Any], path: Path) -> None:
    required(document, ("schema_version", "development_fixture", "publication", "evidence"), path, "document")
    if document["schema_version"] != SCHEMA_VERSION:
        fail(path, f"unsupported schema_version {document['schema_version']!r}")
    if not isinstance(document["development_fixture"], bool):
        fail(path, "development_fixture must be boolean")

    validate_publication(document["publication"], path, "publication")

    evidence = document["evidence"]
    opinions = document.get("opinions", [])
    if not isinstance(evidence, list) or not isinstance(opinions, list):
        fail(path, "evidence and opinions must be arrays")
    # A paper is ingested for the physical evidence it reports, the taxonomic
    # opinions it states, or both; it must contribute at least one.
    if not evidence and not opinions:
        fail(path, "a paper must report physical evidence or taxonomic opinions")
    for index, opinion in enumerate(opinions):
        validate_opinion(opinion, path, f"opinions[{index}]")

    for index, item in enumerate(evidence):
        context = f"evidence[{index}]"
        required(
            item,
            ("id", "physical_key", "evidence_type", "taxon", "specimen", "material", "locality",
             "stratigraphy", "age", "evidence_role", "claims"),
            path,
            context,
        )
        if not item["id"] or not item["physical_key"]:
            fail(path, f"{context} id/physical_key may not be empty")
        if item["evidence_type"] not in EVIDENCE_TYPES:
            fail(path, f"{context} unknown evidence_type {item['evidence_type']!r}")
        if item["evidence_role"] not in EVIDENCE_ROLES:
            fail(path, f"{context} unknown evidence_role {item['evidence_role']!r}")

        if not isinstance(item["taxon"], dict):
            fail(path, f"{context}.taxon must be an object")
        required(item["taxon"], ("name",), path, f"{context}.taxon")

        if not isinstance(item["specimen"], dict):
            fail(path, f"{context}.specimen must be an object")
        specimen = item["specimen"]
        if not any(specimen.get(field) for field in ("institution_code", "catalog_number", "label")):
            fail(path, f"{context}.specimen needs a catalog identity or label")

        if not isinstance(item["locality"], dict):
            fail(path, f"{context}.locality must be an object")
        required(item["locality"], ("name", "country"), path, f"{context}.locality")

        if not isinstance(item["stratigraphy"], dict):
            fail(path, f"{context}.stratigraphy must be an object")

        if not isinstance(item["age"], dict):
            fail(path, f"{context}.age must be an object")
        required(item["age"], ("min_ma", "max_ma", "precision", "method"), path, f"{context}.age")
        age = item["age"]
        if not isinstance(age["min_ma"], (int, float)) or not isinstance(age["max_ma"], (int, float)):
            fail(path, f"{context}.age bounds must be numeric")
        if age["min_ma"] < 0 or age["max_ma"] < age["min_ma"]:
            fail(path, f"{context}.age requires 0 <= min_ma <= max_ma")
        best = age.get("best_ma")
        if best is not None and (
            not isinstance(best, (int, float)) or not age["min_ma"] <= best <= age["max_ma"]
        ):
            fail(path, f"{context}.age.best_ma must fall inside the age interval")
        if age["precision"] not in AGE_PRECISIONS:
            fail(path, f"{context}.age unknown precision {age['precision']!r}")

        if not isinstance(item["material"], list) or not all(
            isinstance(value, str) and value.strip() for value in item["material"]
        ):
            fail(path, f"{context}.material must be an array of non-empty strings")

        if not isinstance(item["claims"], list):
            fail(path, f"{context}.claims must be an array")
        for claim_index, claim in enumerate(item["claims"]):
            if not isinstance(claim, dict):
                fail(path, f"{context}.claims[{claim_index}] must be an object")
            required(claim, ("type", "summary"), path, f"{context}.claims[{claim_index}]")


def validate_publication(publication: Any, path: Path, context: str) -> None:
    if not isinstance(publication, dict):
        fail(path, f"{context} must be an object")
    required(publication, ("id", "title", "year", "authors"), path, context)
    if not publication["id"] or not publication["title"]:
        fail(path, f"{context} id/title may not be empty")
    if not isinstance(publication["year"], int) or not 1600 <= publication["year"] <= 2100:
        fail(path, f"{context} year must be an integer in 1600..2100")
    month = publication.get("month")
    if month is not None and (not isinstance(month, int) or isinstance(month, bool) or not 1 <= month <= 12):
        fail(path, f"{context} month must be null or an integer in 1..12")
    if not isinstance(publication["authors"], list) or not publication["authors"]:
        fail(path, f"{context} authors must be a non-empty array")
    if not all(isinstance(author, str) and author.strip() for author in publication["authors"]):
        fail(path, f"{context} authors must be non-empty strings")


def validate_opinion(opinion: Any, path: Path, context: str) -> None:
    if not isinstance(opinion, dict):
        fail(path, f"{context} must be an object")
    required(opinion, ("id", "taxon", "status", "summary", "source"), path, context)
    if not opinion["id"] or not opinion["taxon"] or not opinion["summary"]:
        fail(path, f"{context} id/taxon/summary may not be empty")
    if opinion["status"] not in OPINION_STATUSES:
        fail(path, f"{context} unknown status {opinion['status']!r}")
    if opinion["source"] not in OPINION_SOURCES:
        fail(path, f"{context} unknown source {opinion['source']!r}")
    if opinion["source"] == "derived_from_occurrence":
        fail(path, f"{context} derived opinions are made by the build, not stored in extraction files")
    specimen = opinion.get("specimen")
    if specimen is not None and (not isinstance(specimen, str) or not specimen.strip()):
        fail(path, f"{context} specimen must be a non-empty string (a physical key or catalog number)")


def validate_creature(document: dict[str, Any], path: Path) -> None:
    required(document, ("schema_version", "id", "name", "hypothesis", "taxa", "rules", "key_events"), path, "creature")
    if document["schema_version"] != CREATURE_SCHEMA_VERSION:
        fail(path, f"unsupported schema_version {document['schema_version']!r}")
    for key in ("id", "name", "hypothesis"):
        if not isinstance(document[key], str) or not document[key].strip():
            fail(path, f"creature {key} must be a non-empty string")
    if not isinstance(document["taxa"], list) or not document["taxa"] or not all(
        isinstance(taxon, str) and taxon.strip() for taxon in document["taxa"]
    ):
        fail(path, "taxa must be a non-empty array of names")

    rules = document["rules"]
    if not isinstance(rules, dict) or set(rules) - {"for", "against"}:
        fail(path, "rules may only hold 'for' and 'against' lists")
    for side, side_rules in rules.items():
        for index, rule in enumerate(side_rules):
            context = f"rules.{side}[{index}]"
            if not isinstance(rule, dict) or not rule.get("status"):
                fail(path, f"{context} needs a status list")
            unknown = set(rule["status"]) - OPINION_STATUSES
            if unknown:
                fail(path, f"{context} unknown statuses {sorted(unknown)}")
            if set(rule["status"]) & USAGE_STATUSES:
                fail(path, f"{context} name usage ({', '.join(sorted(USAGE_STATUSES))}) cannot argue for or against a hypothesis")

    events = document["key_events"]
    if not isinstance(events, list) or not events:
        fail(path, "key_events must be a non-empty array")
    alive = False
    for index, event in enumerate(events):
        context = f"key_events[{index}]"
        if not isinstance(event, dict):
            fail(path, f"{context} must be an object")
        required(event, ("publication_id", "stance"), path, context)
        stance = event["stance"]
        if stance not in STANCE_SIDES:
            fail(path, f"{context} unknown stance {stance!r}")
        rationale = event.get("rationale")
        if rationale is not None and (not isinstance(rationale, str) or not rationale.strip()):
            fail(path, f"{context} rationale must be a non-empty string")
        # The lifeline must be a coherent story: born once, sunk only while
        # in use, and revived only once sunk.
        if index == 0 and stance not in {"proposes", "recorded"}:
            fail(path, "the first key event must propose (or record) the hypothesis")
        if index > 0 and stance in {"proposes", "recorded"}:
            fail(path, f"{context} only the first key event may propose the hypothesis")
        if stance == "revives" and alive:
            fail(path, f"{context} cannot revive a hypothesis that is not sunk")
        if stance in {"supports", "challenges"} and not alive:
            fail(path, f"{context} a sunk hypothesis must be revived before a paper {stance} it")
        if stance in {"proposes", "recorded", "revives"}:
            alive = True
        elif stance == "refutes":
            alive = False


def load_creatures() -> list[tuple[Path, dict[str, Any]]]:
    loaded: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(THEORETICAL.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        validate_creature(document, path)
        loaded.append((path, document))
    return loaded


CREATURE_RANKS = {"genus", "species"}


def corpus_creature_taxa(documents: list[tuple[Path, dict[str, Any]]]) -> dict[str, str]:
    """Every genus and species the corpus reports physical evidence for.

    These are the "official" creatures: each is tracked like a theoretical
    one, as a hypothesis (that the taxon is real) argued over in papers. A
    species also puts its genus on the list.
    """
    taxa: dict[str, str] = {}
    for _, document in documents:
        for item in document["evidence"]:
            name = " ".join(item["taxon"]["name"].split())
            rank = (item["taxon"].get("rank") or "").casefold()
            # "Daspletosaurus sp." is an unnamed species: evidence for the genus only.
            if name.endswith((" sp.", " spp.", " indet.")):
                name, rank = name.split()[0], "genus"
            if rank not in CREATURE_RANKS or not re.fullmatch(r"[A-Z][a-z]+(?: [a-z]+)?", name):
                continue
            taxa[name] = rank
            if rank == "species":
                taxa.setdefault(name.split()[0], "genus")
    return dict(sorted(taxa.items()))


def stable_key(prefix: str, *parts: Any) -> str:
    normalized = "|".join("" if part is None else str(part).strip().lower() for part in parts)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}:{digest}"


def load_documents() -> list[tuple[Path, dict[str, Any]]]:
    loaded: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(EXTRACTED.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        validate_document(document, path)
        loaded.append((path, document))
    if not loaded:
        raise RuntimeError("No extraction JSON found under data/extracted")
    return loaded


def add_identifier(connection: sqlite3.Connection, path: Path, publication_id: str, scheme: str, value: str, provenance: str) -> None:
    existing = connection.execute(
        "SELECT publication_id FROM publication_identifier WHERE scheme = ? AND value = ?", (scheme, value)
    ).fetchone()
    if existing is not None and existing[0] != publication_id:
        fail(path, f"{scheme} {value!r} already identifies {existing[0]!r}: one work is ingested twice")
    connection.execute(
        "INSERT OR IGNORE INTO publication_identifier(publication_id, scheme, value, provenance) VALUES (?, ?, ?, ?)",
        (publication_id, scheme, value, provenance),
    )


def insert_publication(connection: sqlite3.Connection, publication: dict[str, Any], fixture: int, path: Path) -> None:
    doi = normalize_doi(publication.get("doi"))
    url = publication.get("url")
    # A link built from a cosmetically damaged DOI is rebuilt from the repaired one.
    if doi.status == "repaired" and url and url.startswith("https://doi.org/"):
        url = f"https://doi.org/{doi.normalized}"
    connection.execute(
        """INSERT INTO publication(id, doi, doi_raw, doi_status, title, year, month, journal, url, development_fixture)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            publication["id"], doi.normalized, publication.get("doi"), doi.status, publication["title"], publication["year"],
            publication.get("month"), publication.get("journal"), url, fixture,
        ),
    )
    add_identifier(connection, path, publication["id"], "record_id", publication["id"], str(path.relative_to(ROOT)))
    if doi.normalized:
        add_identifier(connection, path, publication["id"], "doi", doi.normalized, f"{path.relative_to(ROOT)} ({doi.status})")
    if publication["id"].startswith("pbdb-ref:"):
        add_identifier(connection, path, publication["id"], "pbdb_reference", publication["id"].split(":", 1)[1], "record id")
    for position, author_name in enumerate(publication["authors"]):
        connection.execute("INSERT OR IGNORE INTO author(name) VALUES (?)", (author_name,))
        author_id = connection.execute(
            "SELECT id FROM author WHERE name = ?", (author_name,)
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO publication_author(publication_id, author_id, author_order) VALUES (?, ?, ?)",
            (publication["id"], author_id, position),
        )


def physical_signature(item: dict[str, Any]) -> tuple[Any, ...]:
    specimen = item["specimen"]
    identity = (
        specimen.get("institution_code"),
        specimen.get("catalog_number"),
    )
    if not any(identity):
        identity = (None, specimen.get("label"))
    return (item["evidence_type"], *identity)


def insert_documents(connection: sqlite3.Connection, documents: list[tuple[Path, dict[str, Any]]]) -> None:
    publication_ids: set[str] = set()
    report_ids: set[str] = set()
    physical_signatures: dict[str, tuple[Any, ...]] = {}

    for path, document in documents:
        publication = document["publication"]
        fixture = int(document["development_fixture"])

        if publication["id"] in publication_ids:
            fail(path, f"duplicate publication id {publication['id']!r}")
        publication_ids.add(publication["id"])

        insert_publication(connection, publication, fixture, path)

        for item in document["evidence"]:
            if item["id"] in report_ids:
                fail(path, f"duplicate publication evidence id {item['id']!r}")
            report_ids.add(item["id"])

            signature = physical_signature(item)
            existing_signature = physical_signatures.get(item["physical_key"])
            if existing_signature is not None and existing_signature != signature:
                fail(
                    path,
                    f"physical_key {item['physical_key']!r} changes physical identity "
                    f"from {existing_signature!r} to {signature!r}",
                )
            physical_signatures[item["physical_key"]] = signature

            specimen = item["specimen"]
            specimen_id = stable_key(
                "specimen",
                specimen.get("institution_code"),
                specimen.get("catalog_number"),
                specimen.get("label") if not specimen.get("catalog_number") else None,
            )
            connection.execute(
                "INSERT OR IGNORE INTO specimen(id, institution_code, catalog_number, label) VALUES (?, ?, ?, ?)",
                (specimen_id, specimen.get("institution_code"), specimen.get("catalog_number"), specimen.get("label")),
            )
            connection.execute(
                "INSERT OR IGNORE INTO physical_evidence(physical_key, evidence_type, specimen_id) VALUES (?, ?, ?)",
                (item["physical_key"], item["evidence_type"], specimen_id),
            )

            taxon = item["taxon"]
            taxon_id = stable_key("taxon", taxon["name"])
            # PBDB occurrences carry PBDB's accepted name; the paper's own
            # identification survives in the reidentification claim.
            from_pbdb = item["physical_key"].startswith("pbdb-occ:")
            taxon_as_published = reported_name(item)
            connection.execute(
                "INSERT OR IGNORE INTO taxon(id, name, rank) VALUES (?, ?, ?)",
                (taxon_id, taxon["name"], taxon.get("rank")),
            )

            locality = item["locality"]
            locality_id = stable_key("locality", locality["country"], locality.get("region"), locality["name"])
            connection.execute(
                """INSERT OR IGNORE INTO locality
                   (id, name, country, region, latitude, longitude, coordinate_uncertainty_km)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    locality_id, locality["name"], locality["country"], locality.get("region"),
                    locality.get("latitude"), locality.get("longitude"), locality.get("coordinate_uncertainty_km"),
                ),
            )

            stratigraphy = item["stratigraphy"]
            formation_id = None
            if any(stratigraphy.get(field) for field in ("formation", "member", "group")):
                formation_id = stable_key(
                    "formation",
                    stratigraphy.get("group"),
                    stratigraphy.get("formation"),
                    stratigraphy.get("member"),
                )
                connection.execute(
                    "INSERT OR IGNORE INTO formation(id, name, member_name, group_name) VALUES (?, ?, ?, ?)",
                    (
                        formation_id,
                        stratigraphy.get("formation"),
                        stratigraphy.get("member"),
                        stratigraphy.get("group"),
                    ),
                )

            age = item["age"]
            connection.execute(
                """INSERT INTO publication_evidence
                   (id, publication_id, physical_key, taxon_id, taxon_as_published, taxon_name_basis, locality_id, formation_id,
                    evidence_role, age_min_ma, age_max_ma, age_best_ma, age_precision, dating_method, age_basis, age_notes,
                    development_fixture)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item["id"], publication["id"], item["physical_key"], taxon_id, taxon_as_published,
                    "pbdb_accepted_name" if from_pbdb else "as_published", locality_id, formation_id,
                    item["evidence_role"], age["min_ma"], age["max_ma"], age.get("best_ma"), age["precision"],
                    age["method"], age.get("basis"), age.get("notes"), fixture,
                ),
            )

            for material in sorted(set(item["material"])):
                connection.execute(
                    "INSERT INTO material(publication_evidence_id, material) VALUES (?, ?)",
                    (item["id"], material),
                )

            for claim_index, claim in enumerate(item["claims"], start=1):
                connection.execute(
                    """INSERT INTO claim
                       (id, publication_evidence_id, claim_type, summary, page, figure, table_ref)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        f"{item['id']}:claim:{claim_index}",
                        item["id"],
                        claim["type"],
                        claim["summary"],
                        claim.get("page"),
                        claim.get("figure"),
                        claim.get("table"),
                    ),
                )


def reported_name(item: dict[str, Any]) -> str:
    """The name the paper itself used for a fossil, qualifiers removed.

    PBDB occurrences store PBDB's accepted name as the taxon and keep the
    original identification in a reidentification claim.
    """
    accepted = " ".join(item["taxon"]["name"].split())
    for claim in item["claims"]:
        match = REIDENTIFICATION.search(claim["summary"]) if claim["type"] == "taxonomic_reidentification" else None
        if match:
            return " ".join(QUALIFIERS.sub(" ", match["identified"]).split()) or accepted
    return accepted


def derived_opinions(publication_id: str, evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Name usage implied by the fossils a paper reports.

    A paper that reports fossils under a name used that name. That is all it
    shows: it is not an argument that the taxon is valid. One usage row is
    recorded per name per paper, under the name the paper itself used (PBDB
    may since have moved the material to another name), and a species also
    records a use of its genus.
    """
    uses: dict[str, dict[str, Any]] = {}

    def use(name: str, accepted: str, reported_as: str, record: str) -> None:
        entry = uses.setdefault(name, {"records": [], "accepted": accepted, "reported_as": reported_as})
        entry["records"].append(record)

    for item in evidence:
        accepted = " ".join(item["taxon"]["name"].split())
        identified = reported_name(item)
        use(identified, accepted, identified, item["id"])
        words = identified.split()
        if len(words) == 2 and words[1].islower():
            use(words[0], accepted, identified, item["id"])

    opinions = []
    for name, entry in sorted(uses.items()):
        count = len(entry["records"])
        records = "fossil record" if count == 1 else "fossil records"
        phrase = f"Reports {count} {records} under the name {name}"
        if entry["reported_as"] != name:
            phrase += f" (as {entry['reported_as']})"
        current = entry["accepted"] if entry["accepted"] not in (name, entry["reported_as"]) else None
        if current:
            phrase += f"; PBDB now files the material as {current}"
        opinions.append({
            "id": stable_key(f"{publication_id}:identified", name),
            "taxon": name,
            "status": "identified_as",
            # The paper named no target: a later database's accepted name is
            # context, not part of the paper's claim.
            "related_taxon": None,
            "current_name": current,
            "basis": "implied",
            "summary": phrase + ".",
            "source": "derived_from_occurrence",
            "source_records": sorted(set(entry["records"])),
        })
    return opinions


def insert_opinions(connection: sqlite3.Connection, documents: list[tuple[Path, dict[str, Any]]]) -> None:
    opinion_ids: set[str] = set()
    for path, document in documents:
        publication_id = document["publication"]["id"]
        opinions = document.get("opinions", []) + derived_opinions(publication_id, document["evidence"])
        for opinion in opinions:
            if opinion["id"] in opinion_ids:
                fail(path, f"duplicate opinion id {opinion['id']!r}")
            opinion_ids.add(opinion["id"])
            claim = classify(opinion)
            records = claim["source_records"] or [f"{path.relative_to(ROOT)}#{opinion['id']}"]
            connection.execute(
                """INSERT INTO taxonomic_opinion
                   (id, publication_id, taxon_name, published_as, name_as_published, status, related_taxon, basis, summary,
                    source, assertion, strength, authority, derivation_rule, source_records, current_name, subject_specimen)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    opinion["id"], publication_id, opinion["taxon"], opinion.get("published_as"), claim["name_as_published"],
                    opinion["status"], opinion.get("related_taxon"), opinion.get("basis"), opinion["summary"], opinion["source"],
                    claim["assertion"], claim["strength"], claim["authority"], claim["derivation_rule"], json.dumps(records),
                    opinion.get("current_name"), opinion.get("specimen"),
                ),
            )


def insert_merged_identifiers(connection: sqlite3.Connection) -> None:
    """PBDB references whose opinions were merged into another record (same
    DOI and title) keep their reference number as an identifier of that record."""
    if not OPINION_IMPORT_MANIFEST.exists():
        return
    manifest = json.loads(OPINION_IMPORT_MANIFEST.read_text(encoding="utf-8"))
    for reference in manifest["references"]:
        path = ROOT / reference["file"]
        publication_id = json.loads(path.read_text(encoding="utf-8"))["publication"]["id"]
        if publication_id == f"pbdb-ref:{reference['reference_id']}":
            continue
        add_identifier(
            connection, OPINION_IMPORT_MANIFEST, publication_id, "pbdb_reference", str(reference["reference_id"]),
            f"{OPINION_IMPORT_MANIFEST.relative_to(ROOT)}: opinions merged by equal DOI and title",
        )


def related_matches(related: str | None, prefixes: list[str]) -> bool:
    if not related:
        return False
    return any(related == prefix or related.startswith(f"{prefix} ") for prefix in prefixes)


def opinion_side(creature: dict[str, Any], opinion: sqlite3.Row) -> str:
    """Which side of the hypothesis an opinion falls on. Against rules win ties.

    Name usage is always "usage": it records that a name was used, and no rule
    can turn it into an argument.
    """
    if opinion["strength"] == "usage":
        return "usage"
    for side in ("against", "for"):
        for rule in creature["rules"].get(side, []):
            if opinion["status"] not in rule["status"]:
                continue
            if "related" in rule and not related_matches(opinion["related_taxon"], rule["related"]):
                continue
            return side
    return "neutral"


# Official creatures follow one written-down rule instead of curated key events.
DEFAULT_RULES = {
    "for": [{"status": ["belongs_to"]}],
    "against": [{"status": [
        "subjective_synonym_of", "objective_synonym_of", "nomen_dubium", "nomen_nudum", "nomen_vanum", "nomen_oblitum",
    ]}],
}


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")


def creature_claims(connection: sqlite3.Connection, creature: dict[str, Any], since: int | None = None) -> list[dict[str, Any]]:
    """Every claim on a creature's names, in publication order, with its side."""
    placeholders = ",".join("?" for _ in creature["taxa"])
    rows = connection.execute(
        f"""SELECT o.*, p.year, p.month FROM taxonomic_opinion o JOIN publication p ON p.id = o.publication_id
            WHERE o.taxon_name IN ({placeholders}) AND p.year >= ?
            ORDER BY p.year, COALESCE(p.month, 0), o.publication_id, o.id""",
        (*creature["taxa"], since if since is not None else -1),
    ).fetchall()
    return [{**dict(row), "side": opinion_side(creature, row)} for row in rows]


def official_creatures(
    connection: sqlite3.Connection,
    documents: list[tuple[Path, dict[str, Any]]],
    curated: list[tuple[Path, dict[str, Any]]],
) -> list[tuple[Path, dict[str, Any]]]:
    covered = {taxon for _, creature in curated for taxon in creature["taxa"]}
    taken = {creature["id"] for _, creature in curated}
    creatures: list[tuple[Path, dict[str, Any]]] = []
    for name, rank in corpus_creature_taxa(documents).items():
        if name in covered or slug(name) in taken:
            continue
        creature = {
            "schema_version": CREATURE_SCHEMA_VERSION,
            "id": slug(name),
            "name": name,
            "scientific_name": name,
            "rank": rank,
            "hypothesis": f"{name} is a real, distinct {rank}.",
            "taxa": [name],
            "rules": DEFAULT_RULES,
            "curated": False,
            "turning_points": TURNING_POINT_RULES_VERSION,
        }
        creature["key_events"] = automatic_key_events(creature_claims(connection, creature))
        if not creature["key_events"]:
            continue
        creatures.append((ROOT / "data" / "extracted", creature))
    return creatures


def insert_creatures(connection: sqlite3.Connection, creatures: list[tuple[Path, dict[str, Any]]]) -> None:
    creature_ids: set[str] = set()
    for path, document in creatures:
        if document["id"] in creature_ids:
            fail(path, f"duplicate creature id {document['id']!r}")
        creature_ids.add(document["id"])
        curated = bool(document.get("curated", True))
        turning_points = str(path.relative_to(ROOT)) if curated else document["turning_points"]
        connection.execute(
            """INSERT INTO theoretical_creature(id, name, scientific_name, hypothesis, turning_points, curated)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (document["id"], document["name"], document.get("scientific_name"), document["hypothesis"], turning_points, int(curated)),
        )
        for taxon in document["taxa"]:
            connection.execute("INSERT INTO creature_taxon(creature_id, taxon_name) VALUES (?, ?)", (document["id"], taxon))

        placeholders = ",".join("?" for _ in document["taxa"])
        previous_year = None
        events: list[dict[str, Any]] = []
        for order, event in enumerate(document["key_events"]):
            context = f"key_events[{order}]"
            publication = connection.execute(
                "SELECT year FROM publication WHERE id = ?", (event["publication_id"],)
            ).fetchone()
            if publication is None:
                fail(path, f"{context} cites {event['publication_id']!r}, which is not an ingested paper")
            if previous_year is not None and publication["year"] < previous_year:
                fail(path, f"{context} key events must be in publication-year order")
            previous_year = publication["year"]
            # The moment must rest on what the ingested paper actually says.
            opinions = connection.execute(
                f"""SELECT * FROM taxonomic_opinion
                    WHERE publication_id = ? AND taxon_name IN ({placeholders})
                    ORDER BY id""",
                (event["publication_id"], *document["taxa"]),
            ).fetchall()
            side = STANCE_SIDES[event["stance"]]
            matching = [
                opinion for opinion in opinions
                if opinion_side(document, opinion) == side and event.get("opinion_id") in (None, opinion["id"])
            ]
            if not matching:
                fail(
                    path,
                    f"{context} says {event['publication_id']!r} {event['stance']} the hypothesis, but that paper "
                    f"holds no ingested opinion on {', '.join(document['taxa'])} arguing '{side}'",
                )
            # Rest on the strongest matching claim; a weaker one than the stance
            # needs is allowed only with a curator's stated reason.
            opinion = max(matching, key=lambda row: (at_least(row["strength"], DECISIVE), at_least(row["strength"], MOVES_STATE)))
            floor = STANCE_FLOOR[event["stance"]]
            if not at_least(opinion["strength"], floor) and not event.get("rationale"):
                fail(
                    path,
                    f"{context} {event['stance']} needs a claim that is at least '{floor}', but "
                    f"{event['publication_id']!r} only holds a '{opinion['strength']}' one; add a rationale or change the stance",
                )
            connection.execute(
                """INSERT INTO hypothesis_event(creature_id, publication_id, opinion_id, stance, event_order, rationale)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (document["id"], event["publication_id"], opinion["id"], event["stance"], order, event.get("rationale")),
            )
            events.append({"publication_id": event["publication_id"], "stance": event["stance"], "opinion_id": opinion["id"]})

        born = connection.execute("SELECT year FROM publication WHERE id = ?", (events[0]["publication_id"],)).fetchone()["year"]
        for sequence, change in enumerate(derive_states(events, creature_claims(connection, document, born))):
            connection.execute(
                """INSERT INTO creature_state(creature_id, sequence, year, state, cause_kind, opinion_id, publication_id, rule)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (document["id"], sequence, change["year"], change["state"], change["kind"], change["opinion_id"],
                 change["publication_id"], STATE_RULES_VERSION),
            )


def publication_summary(connection: sqlite3.Connection, publication_id: str) -> dict[str, Any]:
    row = connection.execute(
        "SELECT id, doi, title, year, month, journal, url FROM publication WHERE id = ?", (publication_id,)
    ).fetchone()
    authors = [
        author[0]
        for author in connection.execute(
            """SELECT a.name FROM publication_author pa JOIN author a ON a.id = pa.author_id
               WHERE pa.publication_id = ? ORDER BY pa.author_order""",
            (publication_id,),
        ).fetchall()
    ]
    return {
        "id": row["id"], "doi": row["doi"], "title": row["title"], "year": row["year"],
        "month": row["month"], "journal": row["journal"], "url": row["url"], "authors": authors,
    }


def opinion_payload(opinion: sqlite3.Row | dict[str, Any], side: str) -> dict[str, Any]:
    """One claim as the browser sees it: what the paper said, under which name,
    how strongly, and where the record came from."""
    payload = {
        "id": opinion["id"],
        "taxon": opinion["taxon_name"],
        "name_as_published": opinion["name_as_published"],
        "status": opinion["status"],
        "related_taxon": opinion["related_taxon"],
        "assertion": opinion["assertion"],
        "strength": opinion["strength"],
        "authority": opinion["authority"],
        "basis": opinion["basis"],
        "source": opinion["source"],
        "source_records": json.loads(opinion["source_records"]),
        "derivation_rule": opinion["derivation_rule"],
        "current_name": opinion["current_name"],
        "specimen": opinion["subject_specimen"],
        "summary": opinion["summary"],
        "side": side,
    }
    # Absent means null; keeps the export small.
    return {key: value for key, value in payload.items() if value is not None}


def paper_side(sides: set[str]) -> str:
    """A paper's overall side: for or against only when it does not argue both ways."""
    argued = sides - {"neutral", "usage"}
    if argued == {"for"} or argued == {"against"}:
        return argued.pop()
    if not argued and sides == {"usage"}:
        return "usage"
    return "neutral"


def export_creatures(connection: sqlite3.Connection, creatures: list[tuple[Path, dict[str, Any]]]) -> dict[str, Any]:
    """Creatures plus one shared table of the publications they cite."""
    publications: dict[str, dict[str, Any]] = {}

    def cite(publication_id: str) -> str:
        if publication_id not in publications:
            publications[publication_id] = publication_summary(connection, publication_id)
        return publication_id

    exported: list[dict[str, Any]] = []
    for _, document in sorted(creatures, key=lambda item: (not item[1].get("curated", True), item[1]["name"])):
        creature_row = connection.execute("SELECT turning_points FROM theoretical_creature WHERE id = ?", (document["id"],)).fetchone()
        key_rows = connection.execute(
            """SELECT e.publication_id, e.stance, e.opinion_id, e.rationale, p.year
               FROM hypothesis_event e JOIN publication p ON p.id = e.publication_id
               WHERE e.creature_id = ? ORDER BY e.event_order""",
            (document["id"],),
        ).fetchall()
        born = key_rows[0]["year"]

        # Every ingested claim on the creature, from its proposal on.
        claims = creature_claims(connection, document, born)
        by_paper: dict[str, list[dict[str, Any]]] = {}
        for claim in claims:
            by_paper.setdefault(claim["publication_id"], []).append(claim)
        payloads = {claim["id"]: opinion_payload(claim, claim["side"]) for claim in claims}

        papers = [
            {
                "publication_id": cite(publication_id),
                "side": paper_side({claim["side"] for claim in paper_claims}),
                "opinions": [payloads[claim["id"]] for claim in paper_claims],
            }
            for publication_id, paper_claims in by_paper.items()
        ]

        key_events = [
            {
                "stance": row["stance"],
                "publication_id": cite(row["publication_id"]),
                "opinion": payloads[row["opinion_id"]],
                "rationale": row["rationale"],
            }
            for row in key_rows
        ]

        states = [
            {
                "year": row["year"],
                "state": row["state"],
                "cause": row["cause_kind"],
                "opinion_id": row["opinion_id"],
                "publication_id": cite(row["publication_id"]),
            }
            for row in connection.execute(
                "SELECT * FROM creature_state WHERE creature_id = ? ORDER BY sequence", (document["id"],)
            ).fetchall()
        ]

        exported.append({
            "id": document["id"],
            "name": document["name"],
            "scientific_name": document.get("scientific_name"),
            "rank": document.get("rank"),
            "curated": document.get("curated", True),
            "hypothesis": document["hypothesis"],
            "taxa": document["taxa"],
            "turning_points": creature_row["turning_points"],
            "state_rule": STATE_RULES_VERSION,
            "evidence_count": len(papers),
            "key_events": key_events,
            "states": states,
            "papers": papers,
        })
    return {
        "schema_version": "fog-of-time.creatures-export/v2",
        "rules": {
            "claims": CLAIM_RULES_VERSION,
            "turning_points": TURNING_POINT_RULES_VERSION,
            "states": STATE_RULES_VERSION,
        },
        "publications": publications,
        "creatures": exported,
    }


def export_web(
    connection: sqlite3.Connection,
    documents: list[tuple[Path, dict[str, Any]]],
    creature_documents: list[tuple[Path, dict[str, Any]]],
    all_creatures: list[tuple[Path, dict[str, Any]]],
) -> None:
    PUBLIC_DATA.mkdir(parents=True, exist_ok=True)
    TIMELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CREATURES_PATH.parent.mkdir(parents=True, exist_ok=True)

    rows = connection.execute(
        """SELECT
             pe.physical_key AS physical_key,
             pe.evidence_type AS evidence_type,
             s.label AS specimen_label,
             t.name AS taxon_name,
             t.rank AS taxon_rank,
             r.taxon_as_published AS taxon_as_published,
             r.taxon_name_basis AS taxon_name_basis,
             l.name AS locality_name,
             l.country AS locality_country,
             l.region AS locality_region,
             f.name AS formation_name,
             r.id AS report_id,
             r.evidence_role AS evidence_role,
             r.age_min_ma AS age_min_ma,
             r.age_max_ma AS age_max_ma,
             r.age_best_ma AS age_best_ma,
             r.age_precision AS age_precision,
             r.dating_method AS dating_method,
             r.age_basis AS age_basis,
             r.development_fixture AS development_fixture,
             p.id AS publication_id,
             p.doi AS publication_doi,
             p.title AS publication_title,
             p.year AS publication_year,
             p.month AS publication_month,
             p.journal AS publication_journal,
             p.url AS publication_url
           FROM publication_evidence r
           JOIN physical_evidence pe ON pe.physical_key = r.physical_key
           JOIN specimen s ON s.id = pe.specimen_id
           JOIN taxon t ON t.id = r.taxon_id
           JOIN locality l ON l.id = r.locality_id
           LEFT JOIN formation f ON f.id = r.formation_id
           JOIN publication p ON p.id = r.publication_id
           ORDER BY pe.physical_key, p.year DESC, r.id"""
    ).fetchall()

    grouped: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        grouped.setdefault(row["physical_key"], []).append(row)

    records: list[dict[str, Any]] = []
    for physical_key, reports in sorted(grouped.items()):
        representative = reports[0]
        report_id = representative["report_id"]
        publication_id = representative["publication_id"]

        authors = [
            row[0]
            for row in connection.execute(
                """SELECT a.name
                   FROM publication_author pa
                   JOIN author a ON a.id = pa.author_id
                   WHERE pa.publication_id = ?
                   ORDER BY pa.author_order""",
                (publication_id,),
            ).fetchall()
        ]
        materials = [
            row[0]
            for row in connection.execute(
                "SELECT material FROM material WHERE publication_evidence_id = ? ORDER BY material",
                (report_id,),
            ).fetchall()
        ]
        claims = [
            {
                "type": row["claim_type"],
                "summary": row["summary"],
                "page": row["page"],
                "figure": row["figure"],
                "table": row["table_ref"],
            }
            for row in connection.execute(
                """SELECT claim_type, summary, page, figure, table_ref
                   FROM claim
                   WHERE publication_evidence_id = ?
                   ORDER BY id""",
                (report_id,),
            ).fetchall()
        ]

        records.append(
            {
                "physical_key": physical_key,
                "evidence_type": representative["evidence_type"],
                "taxon": representative["taxon_name"],
                "taxon_rank": representative["taxon_rank"],
                # What the paper called it, and whether "taxon" is that name or
                # a later database's accepted name for the material.
                "taxon_as_published": representative["taxon_as_published"],
                "taxon_name_basis": representative["taxon_name_basis"],
                "specimen_label": representative["specimen_label"],
                "material": materials,
                "locality": {
                    "name": representative["locality_name"],
                    "country": representative["locality_country"],
                    "region": representative["locality_region"],
                },
                "formation": representative["formation_name"],
                "age": {
                    "min_ma": representative["age_min_ma"],
                    "max_ma": representative["age_max_ma"],
                    "best_ma": representative["age_best_ma"],
                    "precision": representative["age_precision"],
                    "method": representative["dating_method"],
                    "basis": representative["age_basis"],
                },
                "report_count": len(reports),
                "representative_report": {
                    "id": report_id,
                    "evidence_role": representative["evidence_role"],
                    "publication": {
                        "id": publication_id,
                        "doi": representative["publication_doi"],
                        "title": representative["publication_title"],
                        "year": representative["publication_year"],
                        "month": representative["publication_month"],
                        "journal": representative["publication_journal"],
                        "url": representative["publication_url"],
                        "authors": authors,
                    },
                    "claims": claims,
                },
                "development_fixture": bool(representative["development_fixture"]),
            }
        )

    source_payload = [json.loads(path.read_text(encoding="utf-8")) for path, _ in documents + creature_documents]
    digest = hashlib.sha256(
        json.dumps(
            source_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()

    fixture_only = all(document["development_fixture"] for _, document in documents)
    min_age = min(record["age"]["min_ma"] for record in records)
    max_age = max(record["age"]["max_ma"] for record in records)

    manifest = {
        "schema_version": "fog-of-time.web-manifest/v1",
        "dataset_version": "dev-fixtures-v1" if fixture_only else f"sha256:{digest}",
        "physical_evidence_count": len(records),
        "publication_report_count": connection.execute(
            "SELECT COUNT(*) FROM publication_evidence"
        ).fetchone()[0],
        "publication_count": connection.execute(
            "SELECT COUNT(*) FROM publication"
        ).fetchone()[0],
        "theoretical_creature_count": len(creature_documents),
        "creature_count": len(all_creatures),
        "oldest_ma": max(252.0, max_age),
        "youngest_ma": min(66.0, min_age),
        "development_fixture": fixture_only,
        "representative_policy": "latest-publication-report-v0",
        "rules": {
            "publication_identity": IDENTITY_RULES_VERSION,
            "claims": CLAIM_RULES_VERSION,
            "turning_points": TURNING_POINT_RULES_VERSION,
            "states": STATE_RULES_VERSION,
        },
    }

    TIMELINE_PATH.write_text(
        json.dumps(records, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    CREATURES_PATH.write_text(
        json.dumps(export_creatures(connection, all_creatures), separators=(",", ":"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def check_identity(connection: sqlite3.Connection, documents: list[tuple[Path, dict[str, Any]]]) -> dict[str, Any]:
    """Apply the publication identity rules to the whole corpus.

    Two records the rules call the same work fail the build: they must be
    merged in data/extracted first. Every other non-distinct pair (probable
    duplicates, related notices, identifier conflicts) is recorded, not merged.
    """
    records = [{**document["publication"], "path": path} for path, document in documents]
    report = audit_identity(records)
    for pair in report["pairs"]:
        if pair["verdict"] == "distinct":
            continue
        if pair["verdict"] == "same":
            raise ValueError(f"{pair['a']} and {pair['b']} are one publication ({pair['rule']}); merge them in data/extracted")
        connection.execute(
            "INSERT INTO publication_identity_issue(publication_a, publication_b, verdict, rule, detail) VALUES (?, ?, ?, ?, ?)",
            (pair["a"], pair["b"], pair["verdict"], pair["rule"], pair["detail"]),
        )
    return report


def build_database(connection: sqlite3.Connection) -> dict[str, Any]:
    """Validate the checked-in sources and load them into an empty database."""
    documents = load_documents()
    creatures = load_creatures()
    connection.row_factory = sqlite3.Row
    connection.executescript(SQL_SCHEMA.read_text(encoding="utf-8"))
    insert_documents(connection, documents)
    insert_merged_identifiers(connection)
    identity = check_identity(connection, documents)
    insert_opinions(connection, documents)
    insert_creatures(connection, creatures)
    official = official_creatures(connection, documents, creatures)
    for path, creature in official:
        validate_creature(creature, path)
    insert_creatures(connection, official)
    problems = connection.execute("PRAGMA foreign_key_check").fetchall()
    if problems:
        raise ValueError(f"orphan references: {[tuple(row) for row in problems[:10]]}")
    connection.commit()
    return {"documents": documents, "creatures": creatures, "official": official, "identity": identity}


def model_report(connection: sqlite3.Connection, built: dict[str, Any]) -> dict[str, Any]:
    """Counts that show what the build derived and from what."""
    def rows(sql: str) -> list[list[Any]]:
        return [list(row) for row in connection.execute(sql).fetchall()]

    identity = built["identity"]
    verdicts: dict[str, int] = {}
    for pair in identity["pairs"]:
        verdicts[pair["verdict"]] = verdicts.get(pair["verdict"], 0) + 1
    return {
        "schema_version": "fog-of-time.model-report/v1",
        "rules": {
            "publication_identity": IDENTITY_RULES_VERSION,
            "claims": CLAIM_RULES_VERSION,
            "turning_points": TURNING_POINT_RULES_VERSION,
            "states": STATE_RULES_VERSION,
        },
        "extraction_files": len(built["documents"]),
        "publications": connection.execute("SELECT COUNT(*) FROM publication").fetchone()[0],
        "publication_identifiers_by_scheme": rows("SELECT scheme, COUNT(*) FROM publication_identifier GROUP BY 1 ORDER BY 1"),
        "doi_status": rows("SELECT doi_status, COUNT(*) FROM publication GROUP BY 1 ORDER BY 1"),
        "doi_issues": identity["doi_issues"],
        "identity_pairs_by_verdict": dict(sorted(verdicts.items())),
        "identity_pairs_needing_review": [pair for pair in identity["pairs"] if pair["verdict"] != "distinct"],
        "claims": connection.execute("SELECT COUNT(*) FROM taxonomic_opinion").fetchone()[0],
        "claims_by_strength": rows("SELECT strength, COUNT(*) FROM taxonomic_opinion GROUP BY 1 ORDER BY 1"),
        "claims_by_assertion": rows("SELECT assertion, COUNT(*) FROM taxonomic_opinion GROUP BY 1 ORDER BY 1"),
        "claims_by_authority": rows("SELECT authority, COUNT(*) FROM taxonomic_opinion GROUP BY 1 ORDER BY 1"),
        "claims_with_literal_name_differing_from_tracked_name": connection.execute(
            "SELECT COUNT(*) FROM taxonomic_opinion WHERE name_as_published <> taxon_name"
        ).fetchone()[0],
        "evidence_reports_by_name_basis": rows("SELECT taxon_name_basis, COUNT(*) FROM publication_evidence GROUP BY 1 ORDER BY 1"),
        "evidence_reports_reported_under_another_name": connection.execute(
            """SELECT COUNT(*) FROM publication_evidence r JOIN taxon t ON t.id = r.taxon_id WHERE r.taxon_as_published <> t.name"""
        ).fetchone()[0],
        "creatures": rows("SELECT curated, COUNT(*) FROM theoretical_creature GROUP BY 1 ORDER BY 1"),
        "turning_points_by_stance": rows("SELECT stance, COUNT(*) FROM hypothesis_event GROUP BY 1 ORDER BY 1"),
        "curated_turning_points_with_rationale": connection.execute(
            "SELECT COUNT(*) FROM hypothesis_event WHERE rationale IS NOT NULL"
        ).fetchone()[0],
        "final_state_by_creature_kind": rows(
            """SELECT t.curated, s.state, COUNT(*) FROM creature_state s JOIN theoretical_creature t ON t.id = s.creature_id
               WHERE s.sequence = (SELECT MAX(sequence) FROM creature_state x WHERE x.creature_id = s.creature_id)
               GROUP BY 1, 2 ORDER BY 1, 2"""
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=REPORT_PATH, help="where to write the model report JSON")
    args = parser.parse_args()

    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()

    connection = sqlite3.connect(DB_PATH)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        built = build_database(connection)
        export_web(connection, built["documents"], built["creatures"], built["creatures"] + built["official"])
        report = model_report(connection, built)
    finally:
        connection.close()

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Built {DB_PATH.relative_to(ROOT)}")
    print(
        f"Exported {MANIFEST_PATH.relative_to(ROOT)}, {TIMELINE_PATH.relative_to(ROOT)} "
        f"and {CREATURES_PATH.relative_to(ROOT)}"
    )
    print(f"Model report: {args.report}")


if __name__ == "__main__":
    main()
