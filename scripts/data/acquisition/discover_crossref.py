#!/usr/bin/env python3
"""Discover dinosaur-paper candidates from Crossref.

This is an acquisition helper, not part of the website runtime. It writes a
reviewable JSONL queue and never modifies the canonical SQLite database.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_QUERIES = ROOT / "data" / "acquisition" / "discovery_queries.json"
DEFAULT_BENCHMARK = ROOT / "data" / "acquisition" / "benchmark.jsonl"
DEFAULT_OUTPUT = ROOT / "data" / "acquisition" / "candidates.crossref.jsonl"

DINOSAUR_TERMS = (
    "dinosaur", "dinosauria", "theropod", "sauropod", "sauropodomorph",
    "ornithisch", "tyrannosaur", "ceratops", "hadrosaur", "ankylosaur",
    "stegosaur", "dromaeosaur", "troodont", "oviraptor", "iguanodont",
)
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.I)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
    return out


def publication_year(item: dict[str, Any]) -> int | None:
    for field in ("published-print", "published-online", "published", "issued"):
        parts = item.get(field, {}).get("date-parts")
        if parts and parts[0]:
            value = parts[0][0]
            if isinstance(value, int):
                return value
    return None


def first_text(item: dict[str, Any], field: str) -> str | None:
    value = item.get(field)
    if isinstance(value, list) and value:
        return str(value[0])
    if isinstance(value, str):
        return value
    return None


def likely_dinosaur(title: str) -> bool:
    lower = title.lower()
    return any(term in lower for term in DINOSAUR_TERMS)


def fetch_crossref(query: str, rows: int, mailto: str | None) -> list[dict[str, Any]]:
    params = {
        "query.bibliographic": query,
        "filter": "type:journal-article",
        "rows": str(rows),
    }
    if mailto:
        params["mailto"] = mailto
    url = "https://api.crossref.org/v1/works?" + urlencode(params)
    user_agent = "Fog-of-Time/0.1"
    if mailto:
        user_agent += f" (mailto:{mailto})"
    request = Request(url, headers={"User-Agent": user_agent, "Accept": "application/json"})
    with urlopen(request, timeout=30) as response:
        payload = json.load(response)
    return payload.get("message", {}).get("items", [])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queries", type=Path, default=DEFAULT_QUERIES)
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--rows-per-query", type=int, default=25)
    parser.add_argument("--max-candidates", type=int, default=250)
    parser.add_argument("--mailto", default=os.environ.get("CROSSREF_MAILTO"))
    parser.add_argument("--delay-seconds", type=float, default=0.2)
    args = parser.parse_args()

    query_doc = json.loads(args.queries.read_text(encoding="utf-8"))
    queries = query_doc.get("queries", [])
    if not queries:
        raise ValueError("No discovery queries configured")

    benchmark_dois = {
        str(row.get("doi", "")).lower()
        for row in load_jsonl(args.benchmark)
        if row.get("doi")
    }

    aggregate: dict[str, dict[str, Any]] = {}
    matched: dict[str, set[str]] = defaultdict(set)

    for index, query in enumerate(queries):
        print(f"[{index + 1}/{len(queries)}] Crossref: {query}", file=sys.stderr)
        for item in fetch_crossref(query, args.rows_per_query, args.mailto):
            doi = str(item.get("DOI", "")).strip().lower()
            title = first_text(item, "title")
            if not doi or not DOI_RE.match(doi) or not title or not likely_dinosaur(title):
                continue
            if doi in benchmark_dois:
                continue

            score = float(item.get("score") or 0.0)
            previous = aggregate.get(doi)
            if previous is not None and score <= previous["discovery_score"]:
                matched[doi].add(query)
                continue

            aggregate[doi] = {
                "id": f"crossref:{doi}",
                "cohort": "discovery",
                "hand_selected": False,
                "doi": doi,
                "title": title,
                "year": publication_year(item),
                "journal": first_text(item, "container-title"),
                "publisher_url": item.get("URL"),
                "temporal_band": "unknown",
                "target_evidence_types": [],
                "selection_reason": None,
                "access_status": "unknown",
                "metadata_status": "crossref_resolved",
                "extraction_status": "pending",
                "discovered_via": ["crossref"],
                "discovery_score": score,
                "matched_queries": [],
            }
            matched[doi].add(query)

        if index < len(queries) - 1 and args.delay_seconds > 0:
            time.sleep(args.delay_seconds)

    ranked = sorted(
        aggregate.values(),
        key=lambda row: (-row["discovery_score"], row["doi"]),
    )[: max(0, args.max_candidates)]
    for row in ranked:
        row["matched_queries"] = sorted(matched[row["doi"]])

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in ranked),
        encoding="utf-8",
    )
    print(f"Wrote {len(ranked)} candidates to {args.output.relative_to(ROOT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
