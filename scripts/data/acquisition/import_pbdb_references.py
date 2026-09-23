#!/usr/bin/env python3
"""Import a bounded set of dinosaur publication-backed occurrences from PBDB.

This is a networked acquisition step. It snapshots PBDB reference metadata and
occurrence records into Fog of Time's existing reviewable extraction JSON format.
The normal build remains network-free.

PBDB-derived records are deliberately marked as evidence_role=secondary_citation
and evidence_type=fossil_occurrence. They are useful timeline evidence, but are
not presented as equivalent to the hand-verified full-text benchmark.
"""
from __future__ import annotations

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from datetime import datetime, timezone
import io
import json
import math
from pathlib import Path
import re
import sys
import time
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[3]
EXTRACTED = ROOT / "data" / "extracted"
DEFAULT_MANIFEST = ROOT / "data" / "acquisition" / "pbdb-import-manifest.json"
BASE = "https://paleobiodb.org/data1.2"
USER_AGENT = "Fog-of-Time/0.2 (PBDB publication-occurrence snapshot)"

TITLE_SPACE = re.compile(r"\s+")
MIDDLE_JURASSIC_BOUNDARY = 174.7
JURASSIC_CRETACEOUS_BOUNDARY = 143.1
KPG_BOUNDARY = 66.0
TRIASSIC_JURASSIC_BOUNDARY = 201.4
MESOZOIC_OLD = 252.0

PBDB_FILES_GLOB = "pbdb-ref-*.json"


def fetch_text(url: str, timeout: int = 90, retries: int = 4) -> str:
    last: Exception | None = None
    for attempt in range(retries):
        req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/csv,application/json"})
        try:
            with urlopen(req, timeout=timeout) as response:
                return response.read().decode("utf-8", "replace")
        except Exception as exc:
            last = exc
            if attempt + 1 < retries:
                time.sleep(1.0 + attempt * 1.5)
    assert last is not None
    raise last


def read_csv_url(url: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(fetch_text(url))))


def norm_title(value: str | None) -> str:
    if not value:
        return ""
    return TITLE_SPACE.sub(" ", value).strip().casefold()


def float_or_none(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def int_or_none(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def load_existing_publications() -> tuple[set[str], set[str]]:
    dois: set[str] = set()
    titles: set[str] = set()
    for path in EXTRACTED.glob("*.json"):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        publication = doc.get("publication", {})
        doi = publication.get("doi")
        if isinstance(doi, str) and doi.strip():
            dois.add(doi.strip().casefold())
        title = norm_title(publication.get("title"))
        if title:
            titles.add(title)
    return dois, titles


def fetch_occurrences(batch_size: int, max_rows: int) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    offset = 0

    # PBDB accepts numerical age filters on occurrence list queries. Keep the
    # local checks below as a second guard because occurrences can span bounds.
    base_params = {
        "base_name": "Dinosauria",
        "max_ma": str(MESOZOIC_OLD),
        "min_ma": str(KPG_BOUNDARY),
        "show": "coords,loc,ident,refattr,strat",
    }

    while offset < max_rows:
        params = dict(base_params)
        params["limit"] = str(min(batch_size, max_rows - offset))
        params["offset"] = str(offset)
        url = f"{BASE}/occs/list.csv?" + urlencode(params)
        try:
            chunk = read_csv_url(url)
        except HTTPError as exc:
            # Older PBDB deployments have occasionally differed in accepted age
            # filters. Fall back to local filtering without weakening provenance.
            if exc.code != 400 or offset != 0:
                raise
            print("PBDB rejected age filters; retrying with local age filtering", file=sys.stderr)
            base_params.pop("max_ma", None)
            base_params.pop("min_ma", None)
            continue

        if not chunk:
            break
        rows.extend(chunk)
        offset += len(chunk)
        print(f"PBDB occurrences fetched: {len(rows)}", file=sys.stderr)
        if len(chunk) < int(params["limit"]):
            break

    filtered: list[dict[str, str]] = []
    for row in rows:
        older = float_or_none(row.get("max_ma"))
        younger = float_or_none(row.get("min_ma"))
        ref = row.get("reference_no")
        if older is None or younger is None or not ref:
            continue
        if younger > older:
            continue
        # Keep records that overlap the Mesozoic dinosaur interval.
        if older < KPG_BOUNDARY or younger > MESOZOIC_OLD:
            continue
        # Do not let obvious Cenozoic Aves records through when a collection's
        # age range straddles a broad boundary.
        if younger < KPG_BOUNDARY and (row.get("accepted_name") or "") == "Aves":
            continue
        filtered.append(row)
    return filtered


def fetch_reference(ref_id: str) -> dict[str, str] | None:
    url = f"{BASE}/refs/single.csv?" + urlencode({"id": ref_id})
    rows = read_csv_url(url)
    return rows[0] if rows else None


def author_list(ref: dict[str, str]) -> list[str]:
    authors: list[str] = []
    for init_field, last_field in (("author1init", "author1last"), ("author2init", "author2last")):
        init = (ref.get(init_field) or "").strip()
        last = (ref.get(last_field) or "").strip()
        name = " ".join(x for x in (init, last) if x)
        if name:
            authors.append(name)
    others = (ref.get("otherauthors") or "").strip()
    if others:
        # PBDB's otherauthors is free text. Retaining it as one display-author
        # token is safer than incorrectly splitting surname particles or initials.
        authors.append(others)
    return authors


def reference_journal(ref: dict[str, str]) -> str | None:
    for field in ("pubtitle", "r_journal", "r_booktitle", "r_school", "publisher"):
        value = (ref.get(field) or "").strip()
        if value:
            return value
    return None


def occurrence_bucket(rows: list[dict[str, str]]) -> str:
    mids = []
    for row in rows:
        older = float_or_none(row.get("max_ma"))
        younger = float_or_none(row.get("min_ma"))
        if older is not None and younger is not None:
            mids.append((older + younger) / 2.0)
    if not mids:
        return "unknown"
    mids.sort()
    mid = mids[len(mids) // 2]
    if mid >= TRIASSIC_JURASSIC_BOUNDARY:
        return "triassic"
    if mid >= JURASSIC_CRETACEOUS_BOUNDARY:
        return "jurassic"
    return "cretaceous"


def reference_is_usable(
    ref: dict[str, str],
    existing_dois: set[str],
    existing_titles: set[str],
    used_dois: set[str],
    used_titles: set[str],
) -> bool:
    title = (ref.get("reftitle") or "").strip()
    year = int_or_none(ref.get("pubyr"))
    pub_type = (ref.get("publication_type") or "").strip().casefold()
    if not title or year is None or not 1700 <= year <= 2100:
        return False
    # The user asked for papers. PBDB labels normal papers "journal article";
    # serial monographs are also paper-like primary literature and can be long.
    if pub_type not in {"journal article", "serial monograph"}:
        return False

    nt = norm_title(title)
    doi = (ref.get("doi") or "").strip().casefold()
    if nt in existing_titles or nt in used_titles:
        return False
    if doi and (doi in existing_dois or doi in used_dois):
        return False
    return True


def choose_references(
    grouped: dict[str, list[dict[str, str]]],
    refs: dict[str, dict[str, str]],
    paper_count: int,
    max_occurrences_per_reference: int,
    existing_dois: set[str],
    existing_titles: set[str],
) -> list[str]:
    candidates: list[tuple[str, str, int, int]] = []
    used_dois: set[str] = set()
    used_titles: set[str] = set()

    for ref_id, occurrence_rows in grouped.items():
        if not 1 <= len(occurrence_rows) <= max_occurrences_per_reference:
            continue
        ref = refs.get(ref_id)
        if ref is None:
            continue
        if not reference_is_usable(ref, existing_dois, existing_titles, used_dois, used_titles):
            continue
        title_key = norm_title(ref.get("reftitle"))
        doi_key = (ref.get("doi") or "").strip().casefold()
        used_titles.add(title_key)
        if doi_key:
            used_dois.add(doi_key)
        year = int_or_none(ref.get("pubyr")) or 0
        bucket = occurrence_bucket(occurrence_rows)
        candidates.append((ref_id, bucket, year, len(occurrence_rows)))

    # Prefer recent references with richer-but-bounded evidence, then distribute
    # them across Triassic/Jurassic/Cretaceous fossil time.
    candidates.sort(key=lambda x: (-x[2], -x[3], int(x[0])))
    by_bucket: dict[str, list[tuple[str, str, int, int]]] = defaultdict(list)
    for item in candidates:
        by_bucket[item[1]].append(item)

    quotas = {
        "triassic": max(1, round(paper_count * 0.20)),
        "jurassic": max(1, round(paper_count * 0.30)),
        "cretaceous": max(1, round(paper_count * 0.50)),
    }
    selected: list[str] = []
    selected_set: set[str] = set()

    for bucket in ("triassic", "jurassic", "cretaceous"):
        for ref_id, _, _, _ in by_bucket.get(bucket, [])[: quotas[bucket]]:
            selected.append(ref_id)
            selected_set.add(ref_id)

    if len(selected) < paper_count:
        for ref_id, _, _, _ in candidates:
            if ref_id in selected_set:
                continue
            selected.append(ref_id)
            selected_set.add(ref_id)
            if len(selected) >= paper_count:
                break

    if len(selected) < paper_count:
        raise RuntimeError(
            f"Only {len(selected)} usable PBDB references found; requested {paper_count}. "
            f"Try increasing --max-occurrences-per-reference or --max-occurrence-rows."
        )
    return selected[:paper_count]


def country_value(row: dict[str, str]) -> str:
    code = (row.get("cc") or "").strip()
    return code or "Unknown"


def locality_name(row: dict[str, str]) -> str:
    comments = (row.get("geogcomments") or "").strip()
    collection = (row.get("collection_no") or "").strip()
    if comments:
        return f"PBDB collection {collection}: {comments}" if collection else comments
    return f"PBDB collection {collection}" if collection else "PBDB locality not named"


def region_value(row: dict[str, str]) -> str | None:
    parts = [x.strip() for x in (row.get("state") or "", row.get("county") or "") if x.strip()]
    return ", ".join(parts) or None


def occurrence_to_evidence(ref_id: str, row: dict[str, str]) -> dict[str, Any] | None:
    occ = (row.get("occurrence_no") or "").strip()
    collection = (row.get("collection_no") or "").strip()
    taxon = (row.get("accepted_name") or row.get("identified_name") or "").strip()
    rank = (row.get("accepted_rank") or row.get("identified_rank") or "").strip() or None
    older = float_or_none(row.get("max_ma"))
    younger = float_or_none(row.get("min_ma"))
    if not occ or not taxon or older is None or younger is None or younger > older:
        return None

    early = (row.get("early_interval") or "").strip()
    late = (row.get("late_interval") or "").strip()
    interval = early if not late or late == early else f"{early}–{late}"
    identified = (row.get("identified_name") or "").strip()

    claims: list[dict[str, Any]] = [
        {
            "type": "pbdb_occurrence",
            "summary": (
                f"PBDB occurrence {occ} records {taxon} in collection {collection or 'unknown'}, "
                f"linked by PBDB to reference {ref_id}."
            ),
            "page": None,
            "figure": None,
            "table": None,
        }
    ]
    if identified and identified != taxon:
        claims.append(
            {
                "type": "taxonomic_reidentification",
                "summary": f"PBDB stores the original/identified name as {identified} and the accepted name as {taxon}.",
                "page": None,
                "figure": None,
                "table": None,
            }
        )

    return {
        "id": f"pbdb-ref:{ref_id}:occ:{occ}",
        "physical_key": f"pbdb-occ:{occ}",
        "evidence_type": "fossil_occurrence",
        "taxon": {"name": taxon, "rank": rank},
        "specimen": {
            "institution_code": "PBDB",
            "catalog_number": occ,
            "label": f"PBDB occurrence {occ}",
        },
        "material": ["PBDB fossil occurrence record"],
        "locality": {
            "name": locality_name(row),
            "country": country_value(row),
            "region": region_value(row),
            "latitude": float_or_none(row.get("lat")),
            "longitude": float_or_none(row.get("lng")),
            "coordinate_uncertainty_km": None,
        },
        "stratigraphy": {
            "formation": (row.get("formation") or "").strip() or None,
            "member": (row.get("member") or "").strip() or None,
            "group": (row.get("geological_group") or "").strip() or None,
        },
        "age": {
            "min_ma": younger,
            "max_ma": older,
            "best_ma": None if younger != older else younger,
            "precision": "derived_interval" if younger != older else "reported_point",
            "method": "pbdb_collection_numeric_age_range",
            "basis": (
                f"PBDB assigns collection {collection or 'unknown'} to {interval or 'an unnamed interval'} "
                f"with numeric bounds {older:g}–{younger:g} Ma."
            ),
            "notes": (
                f"Database-derived occurrence snapshot from Paleobiology Database reference {ref_id}; "
                "not yet re-verified against the publication full text."
            ),
        },
        "evidence_role": "secondary_citation",
        "claims": claims,
    }


def reference_to_document(ref_id: str, ref: dict[str, str], rows: list[dict[str, str]]) -> dict[str, Any] | None:
    year = int_or_none(ref.get("pubyr"))
    title = (ref.get("reftitle") or "").strip()
    authors = author_list(ref)
    if year is None or not title or not authors:
        return None

    doi = (ref.get("doi") or "").strip() or None
    evidence = [item for row in rows if (item := occurrence_to_evidence(ref_id, row)) is not None]
    if not evidence:
        return None

    return {
        "schema_version": "fog-of-time.paper-extraction/v1",
        "development_fixture": False,
        "publication": {
            "id": f"pbdb-ref:{ref_id}",
            "doi": doi,
            "title": title,
            "year": year,
            "journal": reference_journal(ref),
            "url": f"https://doi.org/{doi}" if doi else f"{BASE}/refs/single.json?id={ref_id}",
            "authors": authors,
        },
        "evidence": evidence,
    }


def safe_ref_filename(ref_id: str) -> str:
    return f"pbdb-ref-{int(ref_id):09d}.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paper-count", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=5000)
    parser.add_argument("--max-occurrence-rows", type=int, default=60000)
    parser.add_argument("--max-occurrences-per-reference", type=int, default=75)
    parser.add_argument("--reference-probe-count", type=int, default=450)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="Manifest path relative to the repository or absolute.",
    )
    parser.add_argument(
        "--replace-existing-pbdb",
        action="store_true",
        help="Delete existing pbdb-ref-*.json files before importing. Default is append-safe.",
    )
    args = parser.parse_args()

    if args.paper_count < 1:
        raise ValueError("--paper-count must be positive")

    existing_dois, existing_titles = load_existing_publications()
    occurrences = fetch_occurrences(args.batch_size, args.max_occurrence_rows)
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in occurrences:
        grouped[row["reference_no"]].append(row)

    # Probe a bounded reference pool chosen by publication year from occurrence
    # metadata and evidence count. Ref details are then authoritative for title,
    # journal, DOI, and authors.
    pool = sorted(
        grouped,
        key=lambda rid: (
            -(int_or_none(grouped[rid][0].get("ref_pubyr")) or 0),
            -len(grouped[rid]),
            int(rid),
        ),
    )[: max(args.reference_probe_count, args.paper_count * 3)]

    refs: dict[str, dict[str, str]] = {}
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        future_map = {executor.submit(fetch_reference, ref_id): ref_id for ref_id in pool}
        for n, future in enumerate(as_completed(future_map), start=1):
            ref_id = future_map[future]
            try:
                ref = future.result()
            except Exception as exc:
                print(f"reference {ref_id} failed: {exc}", file=sys.stderr)
                continue
            if ref:
                refs[ref_id] = ref
            if n % 50 == 0:
                print(f"PBDB references resolved: {n}/{len(pool)}", file=sys.stderr)

    selected = choose_references(
        grouped,
        refs,
        args.paper_count,
        args.max_occurrences_per_reference,
        existing_dois,
        existing_titles,
    )

    # Append is the safe default: existing direct and PBDB publications are
    # already included in the DOI/title exclusion sets above. Replacement is
    # opt-in for deliberately regenerating an entire PBDB snapshot.
    if args.replace_existing_pbdb:
        for path in EXTRACTED.glob(PBDB_FILES_GLOB):
            path.unlink()

    imported: list[dict[str, Any]] = []
    total_occurrences = 0
    for ref_id in selected:
        doc = reference_to_document(ref_id, refs[ref_id], grouped[ref_id])
        if doc is None:
            raise RuntimeError(f"Selected PBDB reference {ref_id} did not produce a valid extraction document")
        out = EXTRACTED / safe_ref_filename(ref_id)
        out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        count = len(doc["evidence"])
        total_occurrences += count
        imported.append(
            {
                "reference_id": int(ref_id),
                "title": doc["publication"]["title"],
                "year": doc["publication"]["year"],
                "doi": doc["publication"]["doi"],
                "occurrence_count": count,
                "fossil_time_bucket": occurrence_bucket(grouped[ref_id]),
                "file": str(out.relative_to(ROOT)),
            }
        )

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    manifest = {
        "schema_version": "fog-of-time.pbdb-import/v1",
        "retrieved_at": now,
        "source": "Paleobiology Database data1.2 API",
        "source_occurrence_endpoint": f"{BASE}/occs/list.csv",
        "source_reference_endpoint": f"{BASE}/refs/single.csv",
        "requested_publications": args.paper_count,
        "imported_publications": len(imported),
        "imported_occurrences": total_occurrences,
        "evidence_role": "secondary_citation",
        "evidence_type": "fossil_occurrence",
        "selection": {
            "base_taxon": "Dinosauria",
            "fossil_age_window_ma": [MESOZOIC_OLD, KPG_BOUNDARY],
            "publication_types": ["journal article", "serial monograph"],
            "max_occurrences_per_reference": args.max_occurrences_per_reference,
            "exclude_existing_dois_and_titles": True,
            "append_safe": not args.replace_existing_pbdb,
            "target_time_mix": {"triassic": 0.20, "jurassic": 0.30, "cretaceous": 0.50},
        },
        "references": imported,
    }
    manifest_path = args.manifest if args.manifest.is_absolute() else ROOT / args.manifest
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(
        f"Imported {len(imported)} PBDB-backed publications with {total_occurrences} fossil occurrences",
        file=sys.stderr,
    )
    for bucket in ("triassic", "jurassic", "cretaceous"):
        count = sum(1 for row in imported if row["fossil_time_bucket"] == bucket)
        print(f"{bucket}: {count} publications", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
