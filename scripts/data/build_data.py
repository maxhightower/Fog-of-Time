#!/usr/bin/env python3
"""Build Fog of Time's local SQLite database and browser-ready static artifacts.

No network access is performed here. Checked-in paper extraction JSON is validated,
normalized into SQLite, and exported to static JSON for the Vite client.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EXTRACTED = ROOT / "data" / "extracted"
SQL_SCHEMA = ROOT / "db" / "schema.sql"
BUILD_DIR = ROOT / "build"
DB_PATH = BUILD_DIR / "fog-of-time.sqlite"
PUBLIC_DATA = ROOT / "public" / "data"
TIMELINE_PATH = PUBLIC_DATA / "timeline" / "all.json"
MANIFEST_PATH = PUBLIC_DATA / "manifest.json"

SCHEMA_VERSION = "fog-of-time.paper-extraction/v1"
EVIDENCE_TYPES = {
    "body_fossil", "trace_fossil", "egg", "nest", "coprolite", "trackway",
    "skin_impression", "feather_impression", "soft_tissue", "bone_histology",
    "tooth", "gastrolith", "pathology", "bite_mark", "biomolecule",
}
EVIDENCE_ROLES = {
    "original_discovery", "original_description", "new_measurement", "new_imaging",
    "redescription", "reinterpretation", "secondary_citation", "review",
}
AGE_PRECISIONS = {
    "explicit_range", "reported_point", "approximate_point", "derived_interval", "unknown",
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

    publication = document["publication"]
    if not isinstance(publication, dict):
        fail(path, "publication must be an object")
    required(publication, ("id", "title", "year", "authors"), path, "publication")
    if not publication["id"] or not publication["title"]:
        fail(path, "publication id/title may not be empty")
    if not isinstance(publication["year"], int) or not 1600 <= publication["year"] <= 2100:
        fail(path, "publication year must be an integer in 1600..2100")
    if not isinstance(publication["authors"], list) or not publication["authors"]:
        fail(path, "publication authors must be a non-empty array")
    if not all(isinstance(author, str) and author.strip() for author in publication["authors"]):
        fail(path, "publication authors must be non-empty strings")

    evidence = document["evidence"]
    if not isinstance(evidence, list) or not evidence:
        fail(path, "evidence must be a non-empty array")

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

        connection.execute(
            """INSERT INTO publication(id, doi, title, year, journal, url, development_fixture)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                publication["id"], publication.get("doi"), publication["title"], publication["year"],
                publication.get("journal"), publication.get("url"), fixture,
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


def export_web(connection: sqlite3.Connection, documents: list[tuple[Path, dict[str, Any]]]) -> None:
    PUBLIC_DATA.mkdir(parents=True, exist_ok=True)
    TIMELINE_PATH.parent.mkdir(parents=True, exist_ok=True)

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
                        "journal": representative["publication_journal"],
                        "url": representative["publication_url"],
                        "authors": authors,
                    },
                    "claims": claims,
                },
                "development_fixture": bool(representative["development_fixture"]),
            }
        )

    source_payload = [json.loads(path.read_text(encoding="utf-8")) for path, _ in documents]
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
        "oldest_ma": max(252.0, max_age),
        "youngest_ma": min(66.0, min_age),
        "development_fixture": fixture_only,
        "representative_policy": "latest-publication-report-v0",
    }

    TIMELINE_PATH.write_text(
        json.dumps(records, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    documents = load_documents()
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()

    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        connection.executescript(SQL_SCHEMA.read_text(encoding="utf-8"))
        insert_documents(connection, documents)
        connection.commit()
        export_web(connection, documents)
    finally:
        connection.close()

    print(f"Built {DB_PATH.relative_to(ROOT)}")
    print(f"Exported {MANIFEST_PATH.relative_to(ROOT)} and {TIMELINE_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
