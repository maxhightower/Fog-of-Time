#!/usr/bin/env python3
"""Ingest the publications behind every tracked creature from PBDB taxonomic opinions.

A PBDB opinion is one publication's verdict on a name: that it belongs to a
parent taxon, is a synonym of another, or is a nomen dubium. Theoretical
creatures are built from these verdicts, so every publication that holds one
is ingested into data/extracted like any other paper.

Creatures are the taxa listed in data/theoretical/*.json (curated theoretical
creatures) plus every genus and species the corpus reports fossils of (the
"official" creatures, as chosen by build_data.corpus_creature_taxa).
For each of them this snapshots PBDB's opinions
and keeps only *primary* ones: opinions whose author and year match the
reference they are recorded from. (PBDB also records an older author's opinion
under a later catalogue; that is second-hand and is skipped.)

Publications already in data/extracted, found by PBDB reference number or DOI,
get the opinions merged into their existing record; the rest are written as new
opinion-only records. This is a networked acquisition step; the normal build
stays offline.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import unicodedata
from typing import Any
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_data import corpus_creature_taxa, load_documents  # noqa: E402
from import_pbdb_references import (  # noqa: E402
    BASE,
    EXTRACTED,
    ROOT,
    author_list,
    int_or_none,
    read_csv_url,
    reference_journal,
    safe_ref_filename,
)

THEORETICAL = ROOT / "data" / "theoretical"
DEFAULT_MANIFEST = ROOT / "data" / "acquisition" / "pbdb-opinion-import-manifest.json"
SCHEMA_VERSION = "fog-of-time.paper-extraction/v1"
THIS_YEAR = datetime.now(timezone.utc).year

STATUS_PHRASES = {
    "belongs_to": "belongs to",
    "subjective_synonym_of": "is a subjective synonym of",
    "objective_synonym_of": "is an objective synonym of",
    "replaced_by": "is replaced by",
    "invalid_subgroup_of": "is an invalid subgroup of",
    "misspelling_of": "is a misspelling of",
    "nomen_dubium": "is a nomen dubium",
    "nomen_nudum": "is a nomen nudum",
    "nomen_vanum": "is a nomen vanum",
    "nomen_oblitum": "is a nomen oblitum",
}
# Statuses whose parent is only where PBDB files the name, not what it is.
NOMINA = {"nomen_dubium", "nomen_nudum", "nomen_vanum", "nomen_oblitum"}


def fold(value: str) -> str:
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().casefold()


def status_key(status: str) -> str:
    return re.sub(r"\s+", "_", status.strip().casefold())


def is_primary(opinion: dict[str, str], ref: dict[str, str]) -> bool:
    """The opinion's author and year are the reference's own."""
    if (opinion.get("pubyr") or "").strip() != (ref.get("pubyr") or "").strip():
        return False
    first_author = fold((ref.get("author1last") or "").strip())
    cited = fold((opinion.get("author") or "").split(" and ")[0].split(" et al")[0].strip())
    return bool(first_author) and (first_author == cited or first_author.endswith(cited) or cited.endswith(first_author))


def opinion_summary(taxon: str, status: str, parent: str | None, published_as: str | None) -> str:
    name = taxon if not published_as or published_as == taxon else f"{taxon} (as {published_as})"
    phrase = STATUS_PHRASES.get(status, status.replace("_", " "))
    if status in NOMINA:
        return f"{name} {phrase}" + (f" (filed under {parent})." if parent else ".")
    return f"{name} {phrase} {parent}." if parent else f"{name} {phrase}."


def same_title(a: str, b: str) -> bool:
    """Titles equal once quotes, punctuation and accents are ignored."""
    return re.sub(r"[^a-z0-9]", "", fold(a)) == re.sub(r"[^a-z0-9]", "", fold(b))


def to_opinion(row: dict[str, str]) -> dict[str, Any]:
    status = status_key(row["status"])
    taxon = row["taxon_name"].strip()
    parent = (row.get("parent_name") or "").strip() or None
    published_as = (row.get("child_name") or "").strip() or None
    number = row["opinion_no"].split(":")[-1]
    return {
        "id": f"pbdb-opinion:{number}",
        "taxon": taxon,
        "published_as": published_as if published_as != taxon else None,
        "status": status,
        "related_taxon": parent,
        "basis": (row.get("basis") or "").strip() or None,
        "summary": opinion_summary(taxon, status, parent, published_as),
        "source": "pbdb_opinion",
    }


NAME_BATCH = 40
REF_BATCH = 100


def load_creature_taxa() -> list[str]:
    taxa: list[str] = []
    for path in sorted(THEORETICAL.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        for taxon in document.get("taxa", []):
            if taxon not in taxa:
                taxa.append(taxon)
    for taxon in corpus_creature_taxa(load_documents()):
        if taxon not in taxa:
            taxa.append(taxon)
    return taxa


def fetch_opinions(names: list[str]) -> list[dict[str, str]]:
    """Opinions on these names; a batch PBDB rejects is retried name by name."""
    url = f"{BASE}/taxa/opinions.csv?" + urlencode({"name": ",".join(names), "op_type": "all", "show": "basis"})
    try:
        rows = read_csv_url(url)
        if all(row.get("reference_no") is not None for row in rows):
            return rows
    except Exception:
        pass
    if len(names) == 1:
        print(f"PBDB has no opinions for {names[0]}", file=sys.stderr)
        return []
    return [row for name in names for row in fetch_opinions([name])]


def fetch_references(ref_ids: list[str]) -> dict[str, dict[str, str]]:
    refs: dict[str, dict[str, str]] = {}
    for start in range(0, len(ref_ids), REF_BATCH):
        batch = ref_ids[start:start + REF_BATCH]
        for row in read_csv_url(f"{BASE}/refs/list.csv?" + urlencode({"ref_id": ",".join(batch)})):
            if row.get("reference_no"):
                refs[row["reference_no"].split(":")[-1]] = row
        print(f"PBDB references resolved: {min(start + REF_BATCH, len(ref_ids))}/{len(ref_ids)}", file=sys.stderr)
    return refs


def existing_documents() -> tuple[dict[str, Path], dict[str, Path]]:
    by_ref: dict[str, Path] = {}
    by_doi: dict[str, Path] = {}
    for path in EXTRACTED.glob("*.json"):
        publication = json.loads(path.read_text(encoding="utf-8"))["publication"]
        if publication["id"].startswith("pbdb-ref:"):
            by_ref[publication["id"].split(":", 1)[1]] = path
        if publication.get("doi"):
            by_doi[publication["doi"].strip().casefold()] = path
    return by_ref, by_doi


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()

    taxa = load_creature_taxa()
    if not taxa:
        print("No taxa listed in data/theoretical/*.json", file=sys.stderr)
        return 1

    rows_by_ref: dict[str, list[dict[str, str]]] = {}
    seen: set[str] = set()
    for start in range(0, len(taxa), NAME_BATCH):
        for row in fetch_opinions(taxa[start:start + NAME_BATCH]):
            if row.get("opinion_no") in seen or not row.get("reference_no"):
                continue
            seen.add(row["opinion_no"])
            rows_by_ref.setdefault(row["reference_no"].split(":")[-1], []).append(row)
        print(f"Opinions fetched for {min(start + NAME_BATCH, len(taxa))}/{len(taxa)} taxa", file=sys.stderr)
    refs = fetch_references(sorted(rows_by_ref, key=int))

    by_ref, by_doi = existing_documents()
    imported: list[dict[str, Any]] = []
    skipped_secondary = 0
    skipped_unpublished = 0
    for ref_id in sorted(rows_by_ref, key=int):
        ref = refs.get(ref_id)
        if ref is None:
            continue
        # Only publications are ingested: PBDB's "unpublished" references are
        # compilers' own opinion lists (some carry placeholder future years).
        year = int_or_none(ref.get("pubyr"))
        if (ref.get("publication_type") or "").strip() == "unpublished" or (year is not None and year > THIS_YEAR):
            skipped_unpublished += 1
            continue
        primary = [row for row in rows_by_ref[ref_id] if is_primary(row, ref)]
        skipped_secondary += len(rows_by_ref[ref_id]) - len(primary)
        if not primary:
            continue
        opinions = sorted((to_opinion(row) for row in primary), key=lambda opinion: opinion["id"])

        doi = (ref.get("doi") or "").strip() or None
        path = by_ref.get(ref_id)
        if path is None and doi and doi.casefold() in by_doi:
            # PBDB sometimes enters one paper twice (e.g. online and print
            # years). Same DOI and title: one paper, so its opinions merge.
            other = json.loads(by_doi[doi.casefold()].read_text(encoding="utf-8"))["publication"]
            title = (ref.get("reftitle") or ref.get("pubtitle") or "")
            if same_title(other["title"], title) is False:
                print(f"PBDB reference {ref_id} shares DOI {doi} with a different title; DOI dropped", file=sys.stderr)
                doi = None
            else:
                path = by_doi[doi.casefold()]
        if path is not None:
            document = json.loads(path.read_text(encoding="utf-8"))
            ids = {opinion["id"] for opinion in opinions}
            kept = [opinion for opinion in document.get("opinions", []) if opinion["id"] not in ids]
            document["opinions"] = sorted(kept + opinions, key=lambda opinion: opinion["id"])
            action = "merged"
        else:
            year = int_or_none(ref.get("pubyr"))
            # Whole books carry their title in pubtitle, not reftitle.
            is_book = not (ref.get("reftitle") or "").strip()
            title = (ref.get("reftitle") or ref.get("pubtitle") or "").strip()
            authors = author_list(ref)
            if year is None or not title or not authors:
                print(f"PBDB reference {ref_id} lacks year/title/authors; skipped", file=sys.stderr)
                continue
            path = EXTRACTED / safe_ref_filename(ref_id)
            document = {
                "schema_version": SCHEMA_VERSION,
                "development_fixture": False,
                "publication": {
                    "id": f"pbdb-ref:{ref_id}",
                    "doi": doi,
                    "title": title,
                    "year": year,
                    "journal": (ref.get("publisher") or "").strip() or None if is_book else reference_journal(ref),
                    "url": f"https://doi.org/{doi}" if doi else f"{BASE}/refs/single.json?id={ref_id}",
                    "authors": authors,
                },
                "evidence": [],
                "opinions": opinions,
            }
            action = "created"
        path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        by_ref[ref_id] = path
        if document["publication"].get("doi"):
            by_doi.setdefault(document["publication"]["doi"].casefold(), path)
        imported.append({
            "reference_id": int(ref_id),
            "file": str(path.relative_to(ROOT)),
            "action": action,
            "opinions": [opinion["id"] for opinion in opinions],
        })

    manifest = {
        "schema_version": "fog-of-time.pbdb-opinion-import/v1",
        "retrieved_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source": "Paleobiology Database data1.2 API",
        "source_opinion_endpoint": f"{BASE}/taxa/opinions.csv",
        "source_reference_endpoint": f"{BASE}/refs/single.csv",
        "taxa": taxa,
        "selection": "primary opinions only: opinion author and year match the reference",
        "skipped_secondary_opinions": skipped_secondary,
        "skipped_unpublished_references": skipped_unpublished,
        "publications_created": sum(1 for item in imported if item["action"] == "created"),
        "publications_merged": sum(1 for item in imported if item["action"] == "merged"),
        "references": imported,
    }
    args.manifest.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"Opinions from {len(imported)} publications "
        f"({manifest['publications_created']} new, {manifest['publications_merged']} merged); "
        f"{skipped_secondary} second-hand opinions skipped",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
