#!/usr/bin/env python3
"""Build Fog of Time's local SQLite database and browser-ready static artifacts.

No network access is performed here. Checked-in paper extraction JSON is validated,
normalized into SQLite, and exported to static JSON for the Vite client.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
import sqlite3
from typing import Any

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
CREATURE_SCHEMA_VERSION = "fog-of-time.theoretical-creature/v2"
# A taxonomic opinion is one paper's verdict on a name. Most come from PBDB;
# "identified_as" is derived from a paper's own occurrence identifications and
# "sister_to" records a phylogenetic placement stated in a paper.
OPINION_STATUSES = {
    "belongs_to", "subjective_synonym_of", "objective_synonym_of", "replaced_by", "invalid_subgroup_of",
    "misspelling_of", "nomen_dubium", "nomen_nudum", "nomen_vanum", "nomen_oblitum", "sister_to", "identified_as",
}
OPINION_SOURCES = {"pbdb_opinion", "full_text", "abstract", "derived_from_occurrence"}
# The moments that change a hypothesis's life, and which side of the argument
# the cited paper's opinion must be on for the moment to stand.
STANCE_SIDES = {
    "proposes": "for", "supports": "for", "revives": "for", "confirms": "for",
    "challenges": "against", "refutes": "against",
}
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
        # The lifeline must be a coherent story: born once, dies only while
        # alive, and revived only once dead.
        if index == 0 and stance != "proposes":
            fail(path, "the first key event must propose the hypothesis")
        if index > 0 and stance == "proposes":
            fail(path, f"{context} only the first key event may propose the hypothesis")
        if stance == "revives" and alive:
            fail(path, f"{context} cannot revive a hypothesis that is still alive")
        if stance in {"supports", "challenges", "confirms"} and not alive:
            fail(path, f"{context} a refuted hypothesis must be revived before a paper {stance} it")
        if stance in {"proposes", "revives"}:
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


def insert_publication(connection: sqlite3.Connection, publication: dict[str, Any], fixture: int) -> None:
    connection.execute(
        """INSERT INTO publication(id, doi, title, year, month, journal, url, development_fixture)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            publication["id"], publication.get("doi"), publication["title"], publication["year"],
            publication.get("month"), publication.get("journal"), publication.get("url"), fixture,
        ),
    )
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

        insert_publication(connection, publication, fixture)

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
                   (id, publication_id, physical_key, taxon_id, locality_id, formation_id, evidence_role,
                    age_min_ma, age_max_ma, age_best_ma, age_precision, dating_method, age_basis, age_notes, development_fixture)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item["id"], publication["id"], item["physical_key"], taxon_id, locality_id, formation_id,
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


def derived_opinions(publication_id: str, evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Opinions implied by a paper's own identifications of its fossils.

    When a paper identifies material under a name the accepted taxonomy has
    since replaced, the paper is evidence that the name was in use; one opinion
    is recorded per name per paper.
    """
    uses: dict[tuple[str, str], int] = {}
    for item in evidence:
        for claim in item["claims"]:
            if claim["type"] != "taxonomic_reidentification":
                continue
            match = REIDENTIFICATION.search(claim["summary"])
            if not match:
                continue
            identified = " ".join(QUALIFIERS.sub(" ", match["identified"]).split())
            accepted = match["accepted"].strip()
            if identified and identified != accepted:
                uses[(identified, accepted)] = uses.get((identified, accepted), 0) + 1
    opinions = []
    for (identified, accepted), count in sorted(uses.items()):
        records = "record" if count == 1 else "records"
        opinions.append({
            "id": stable_key(f"{publication_id}:identified", identified),
            "taxon": identified,
            "status": "identified_as",
            "related_taxon": accepted,
            "basis": "implied",
            "summary": f"Identifies {count} fossil {records} as {identified} (the accepted name is now {accepted}).",
            "source": "derived_from_occurrence",
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
            connection.execute(
                """INSERT INTO taxonomic_opinion
                   (id, publication_id, taxon_name, published_as, status, related_taxon, basis, summary, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    opinion["id"], publication_id, opinion["taxon"], opinion.get("published_as"), opinion["status"],
                    opinion.get("related_taxon"), opinion.get("basis"), opinion["summary"], opinion["source"],
                ),
            )


def related_matches(related: str | None, prefixes: list[str]) -> bool:
    if not related:
        return False
    return any(related == prefix or related.startswith(f"{prefix} ") for prefix in prefixes)


def opinion_side(creature: dict[str, Any], opinion: sqlite3.Row) -> str:
    """Which side of the hypothesis an opinion falls on. Against rules win ties."""
    for side in ("against", "for"):
        for rule in creature["rules"].get(side, []):
            if opinion["status"] not in rule["status"]:
                continue
            if "related" in rule and not related_matches(opinion["related_taxon"], rule["related"]):
                continue
            return side
    return "neutral"


def insert_creatures(connection: sqlite3.Connection, creatures: list[tuple[Path, dict[str, Any]]]) -> None:
    creature_ids: set[str] = set()
    for path, document in creatures:
        if document["id"] in creature_ids:
            fail(path, f"duplicate creature id {document['id']!r}")
        creature_ids.add(document["id"])
        connection.execute(
            "INSERT INTO theoretical_creature(id, name, scientific_name, hypothesis) VALUES (?, ?, ?, ?)",
            (document["id"], document["name"], document.get("scientific_name"), document["hypothesis"]),
        )
        for taxon in document["taxa"]:
            connection.execute("INSERT INTO creature_taxon(creature_id, taxon_name) VALUES (?, ?)", (document["id"], taxon))

        placeholders = ",".join("?" for _ in document["taxa"])
        previous_year = None
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
            matching = [opinion for opinion in opinions if opinion_side(document, opinion) == side]
            if not matching:
                fail(
                    path,
                    f"{context} says {event['publication_id']!r} {event['stance']} the hypothesis, but that paper "
                    f"holds no ingested opinion on {', '.join(document['taxa'])} arguing '{side}'",
                )
            connection.execute(
                """INSERT INTO hypothesis_event(creature_id, publication_id, opinion_id, stance, event_order)
                   VALUES (?, ?, ?, ?, ?)""",
                (document["id"], event["publication_id"], matching[0]["id"], event["stance"], order),
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


def opinion_payload(opinion: sqlite3.Row, side: str) -> dict[str, Any]:
    return {
        "id": opinion["id"],
        "taxon": opinion["taxon_name"],
        "status": opinion["status"],
        "related_taxon": opinion["related_taxon"],
        "basis": opinion["basis"],
        "source": opinion["source"],
        "summary": opinion["summary"],
        "side": side,
    }


def export_creatures(connection: sqlite3.Connection, creatures: list[tuple[Path, dict[str, Any]]]) -> list[dict[str, Any]]:
    exported: list[dict[str, Any]] = []
    for _, document in sorted(creatures, key=lambda item: item[1]["name"]):
        placeholders = ",".join("?" for _ in document["taxa"])
        key_rows = connection.execute(
            """SELECT e.publication_id, e.stance, e.opinion_id, p.year
               FROM hypothesis_event e JOIN publication p ON p.id = e.publication_id
               WHERE e.creature_id = ? ORDER BY e.event_order""",
            (document["id"],),
        ).fetchall()
        born = key_rows[0]["year"]

        # Every ingested paper with an opinion on the creature, from its proposal on.
        opinions = connection.execute(
            f"""SELECT o.*, p.year FROM taxonomic_opinion o JOIN publication p ON p.id = o.publication_id
                WHERE o.taxon_name IN ({placeholders}) AND p.year >= ?
                ORDER BY p.year, o.publication_id, o.id""",
            (*document["taxa"], born),
        ).fetchall()
        by_paper: dict[str, list[sqlite3.Row]] = {}
        for opinion in opinions:
            by_paper.setdefault(opinion["publication_id"], []).append(opinion)

        papers = []
        for publication_id, paper_opinions in by_paper.items():
            sides = {opinion_side(document, opinion) for opinion in paper_opinions}
            side = "for" if sides == {"for"} or sides == {"for", "neutral"} else (
                "against" if sides == {"against"} or sides == {"against", "neutral"} else "neutral"
            )
            papers.append({
                "publication": publication_summary(connection, publication_id),
                "side": side,
                "opinions": [opinion_payload(opinion, opinion_side(document, opinion)) for opinion in paper_opinions],
            })

        key_events = []
        for row in key_rows:
            opinion = connection.execute("SELECT * FROM taxonomic_opinion WHERE id = ?", (row["opinion_id"],)).fetchone()
            key_events.append({
                "stance": row["stance"],
                "publication": publication_summary(connection, row["publication_id"]),
                "opinion": opinion_payload(opinion, STANCE_SIDES[row["stance"]]),
            })

        exported.append({
            "id": document["id"],
            "name": document["name"],
            "scientific_name": document.get("scientific_name"),
            "hypothesis": document["hypothesis"],
            "taxa": document["taxa"],
            "evidence_count": len(papers),
            "key_events": key_events,
            "papers": papers,
        })
    return exported


def export_web(
    connection: sqlite3.Connection,
    documents: list[tuple[Path, dict[str, Any]]],
    creature_documents: list[tuple[Path, dict[str, Any]]],
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
        "oldest_ma": max(252.0, max_age),
        "youngest_ma": min(66.0, min_age),
        "development_fixture": fixture_only,
        "representative_policy": "latest-publication-report-v0",
    }

    TIMELINE_PATH.write_text(
        json.dumps(records, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    CREATURES_PATH.write_text(
        json.dumps(export_creatures(connection, creature_documents), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    documents = load_documents()
    creatures = load_creatures()
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()

    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        connection.executescript(SQL_SCHEMA.read_text(encoding="utf-8"))
        insert_documents(connection, documents)
        insert_opinions(connection, documents)
        insert_creatures(connection, creatures)
        connection.commit()
        export_web(connection, documents, creatures)
    finally:
        connection.close()

    print(f"Built {DB_PATH.relative_to(ROOT)}")
    print(
        f"Exported {MANIFEST_PATH.relative_to(ROOT)}, {TIMELINE_PATH.relative_to(ROOT)} "
        f"and {CREATURES_PATH.relative_to(ROOT)}"
    )


if __name__ == "__main__":
    main()
