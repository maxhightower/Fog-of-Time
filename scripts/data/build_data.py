#!/usr/bin/env python3
"""Build Fog of Time's local SQLite database and browser-ready static artifacts.

This script performs no network access. It reads checked-in paper extraction JSON,
validates the v1 contract, normalizes records into SQLite, and exports compact JSON
for the Vite client.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
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
        if item["evidence_type"] not in EVIDENCE_TYPES:
            fail(path, f"{context} unknown evidence_type {item['evidence_type']!r}")
        if item["evidence_role"] not in EVIDENCE_ROLES:
            fail(path, f"{context} unknown evidence_role {item['evidence_role']!r}")

        required(item["taxon"], ("name",), path, f"{context}.taxon")
        required(item["locality"], ("name", "country"), path, f"{context}.locality")
        required(item["age"], ("min_ma", "max_ma", "method"), path, f"{context}.age")
        age = item["age"]
        if not isinstance(age["min_ma"], (int, float)) or not isinstance(age["max_ma"], (int, float)):
            fail(path, f"{context}.age bounds must be numeric")
        if age["min_ma"] < 0 or age["max_ma"] < age["min_ma"]:
            fail(path, f"{context}.age requires 0 <= min_ma <= max_ma")
        best = age.get("best_ma")
        if best is not None and not age["min_ma"] <= best <= age["max_ma"]:
            fail(path, f"{context}.age.best_ma must fall inside the age interval")
        if not isinstance(item["material"], list) or not all(isinstance(x, str) and x for x in item["material"]):
            fail(path, f"{context}.material must be an array of non-empty strings")
        if not isinstance(item["claims"], list):
            fail(path, f"{context}.claims must be an array")
        for claim_index, claim in enumerate(item["claims"]):
            required(claim, ("type", "summary"), path, f"{context}.claims[{claim_index}]")


def key(prefix: str, *parts: Any) -> str:
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


def insert_documents(connection: sqlite3.Connection, documents: list[tuple[Path, dict[str, Any]]]) -> None:
    report_ids: set[str] = set()
    for _, document in documents:
        publication = document["publication"]
        fixture = int(document["development_fixture"])
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
            author_id = connection.execute("SELECT id FROM author WHERE name = ?", (author_name,)).fetchone()[0]
            connection.execute(
                "INSERT INTO publication_author(publication_id, author_id, author_order) VALUES (?, ?, ?)",
                (publication["id"], author_id, position),
            )

        for item in document["evidence"]:
            if item["id"] in report_ids:
                raise ValueError(f"Duplicate publication evidence id: {item['id']}")
            report_ids.add(item["id"])

            specimen = item["specimen"]
            specimen_id = key(
                "specimen",
                specimen.get("institution_code"),
                specimen.get("catalog_number"),
                specimen.get("label"),
                item["physical_key"],
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
            taxon_id = key("taxon", taxon["name"])
            connection.execute(
                "INSERT OR IGNORE INTO taxon(id, name, rank) VALUES (?, ?, ?)",
                (taxon_id, taxon["name"], taxon.get("rank")),
            )

            locality = item["locality"]
            locality_id = key("locality", locality["country"], locality.get("region"), locality["name"])
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
                formation_id = key("formation", stratigraphy.get("group"), stratigraphy.get("formation"), stratigraphy.get("member"))
                connection.execute(
                    "INSERT OR IGNORE INTO formation(id, name, member_name, group_name) VALUES (?, ?, ?, ?)",
                    (formation_id, stratigraphy.get("formation"), stratigraphy.get("member"), stratigraphy.get("group")),
                )

            age = item["age"]
            connection.execute(
                """INSERT INTO publication_evidence
                   (id, publication_id, physical_key, taxon_id, locality_id, formation_id, evidence_role,
                    age_min_ma, age_max_ma, age_best_ma, dating_method, age_basis, age_notes, development_fixture)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item["id"], publication["id"], item["physical_key"], taxon_id, locality_id, formation_id,
                    item["evidence_role"], age["min_ma"], age["max_ma"], age.get("best_ma"), age["method"],
                    age.get("basis"), age.get("notes"), fixture,
                ),
            )

            for material in sorted(set(item["material"])):
                connection.execute(
                    "INSERT INTO material(publication_evidence_id, material) VALUES (?, ?)",
                    (item["id"], material),
                )

            for claim_index, claim in enumerate(item["claims"]):
                claim_id = f"{item['id']}:claim:{claim_index + 1}"
                connection.execute(
                    """INSERT INTO claim
                       (id, publication_evidence_id, claim_type, summary, page, figure, table_ref)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        claim_id, item["id"], claim["type"], claim["summary"], claim.get("page"),
                        claim.get("figure"), claim.get("table"),
                    ),
                )


def export_web(connection: sqlite3.Connection, documents: list[tuple[Path, dict[str, Any]]]) -> None:
    PUBLIC_DATA.mkdir(parents=True, exist_ok=True)
    TIMELINE_PATH.parent.mkdir(parents=True, exist_ok=True)

    rows = connection.execute(
        """SELECT pe.physical_key, pe.evidence_type, s.label, t.name, t.rank,
                  l.name, l.country, l.region, f.name,
                  r.id, r.evidence_role, r.age_min_ma, r.age_max_ma, r.age_best_ma,
                  r.dating_method, r.age_basis, r.development_fixture,
                  p.id, p.doi, p.title, p.year, p.journal, p.url
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
        report_id = representative["id"]
        authors = [
            row[0]
            for row in connection.execute(
                """SELECT a.name
                   FROM publication_author pa JOIN author a ON a.id = pa.author_id
                   WHERE pa.publication_id = ?
                   ORDER BY pa.author_order""",
                (representative["id"] and representative["id"].split(":e")[0] if False else representative["publication_id"] if "publication_id" in representative.keys() else representative[17],),
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
                   FROM claim WHERE publication_evidence_id = ? ORDER BY id""",
                (report_id,),
            ).fetchall()
        ]
        publication_id = representative[17]
        authors = [
            row[0]
            for row in connection.execute(
                """SELECT a.name
                   FROM publication_author pa JOIN author a ON a.id = pa.author_id
                   WHERE pa.publication_id = ? ORDER BY pa.author_order""",
                (publication_id,),
            ).fetchall()
        ]

        records.append(
            {
                "physical_key": physical_key,
                "evidence_type": representative["evidence_type"],
                "taxon": representative["name"],
                "taxon_rank": representative["rank"],
                "specimen_label": representative["label"],
                "material": materials,
                "locality": {
                    "name": representative[5],
                    "country": representative["country"],
                    "region": representative["region"],
                },
                "formation": representative[8],
                "age": {
                    "min_ma": representative["age_min_ma"],
                    "max_ma": representative["age_max_ma"],
                    "best_ma": representative["age_best_ma"],
                    "method": representative["dating_method"],
                    "basis": representative["age_basis"],
                },
                "report_count": len(reports),
                "representative_report": {
                    "id": report_id,
                    "evidence_role": representative["evidence_role"],
                    "publication": {
                        "id": publication_id,
                        "doi": representative[18],
                        "title": representative[19],
                        "year": representative[20],
                        "journal": representative[21],
                        "url": representative[22],
                        "authors": authors,
                    },
                    "claims": claims,
                },
                "development_fixture": bool(representative["development_fixture"]),
            }
        )

    source_payload = [
        json.loads(path.read_text(encoding="utf-8"))
        for path, _ in documents
    ]
    digest = hashlib.sha256(
        json.dumps(source_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    fixture_only = all(document["development_fixture"] for _, document in documents)
    min_age = min(record["age"]["min_ma"] for record in records)
    max_age = max(record["age"]["max_ma"] for record in records)
    publication_count = connection.execute("SELECT COUNT(*) FROM publication").fetchone()[0]
    report_count = connection.execute("SELECT COUNT(*) FROM publication_evidence").fetchone()[0]

    manifest = {
        "schema_version": "fog-of-time.web-manifest/v1",
        "dataset_version": "dev-fixtures-v1" if fixture_only else f"sha256:{digest}",
        "physical_evidence_count": len(records),
        "publication_report_count": report_count,
        "publication_count": publication_count,
        "oldest_ma": max(252.0, max_age),
        "youngest_ma": min(66.0, min_age),
        "development_fixture": fixture_only,
        "representative_policy": "latest-publication-report-v0",
    }

    TIMELINE_PATH.write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


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
