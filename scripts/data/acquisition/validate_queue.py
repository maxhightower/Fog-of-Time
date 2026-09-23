#!/usr/bin/env python3
"""Validate acquisition queues without making network requests."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BENCHMARK = ROOT / "data" / "acquisition" / "benchmark.jsonl"
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.I)
TEMPORAL_BANDS = {
    "triassic", "early_jurassic", "middle_jurassic", "late_jurassic",
    "early_cretaceous", "late_cretaceous", "mixed", "unknown",
}
ACCESS = {"open_access", "needs_access", "unknown"}
METADATA = {"publisher_verified", "crossref_resolved", "discovered", "needs_review"}
EXTRACTION = {"pending", "ready", "extracted", "reviewed", "admitted", "rejected"}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: row must be an object")
        value["_line"] = line_number
        rows.append(value)
    return rows


def validate_row(path: Path, row: dict[str, Any]) -> None:
    line = row["_line"]
    required = (
        "id", "cohort", "doi", "title", "year", "temporal_band",
        "target_evidence_types", "access_status", "metadata_status",
        "extraction_status", "discovered_via",
    )
    missing = [field for field in required if field not in row]
    if missing:
        raise ValueError(f"{path}:{line}: missing {missing}")

    doi = row["doi"]
    if doi is not None and (not isinstance(doi, str) or not DOI_RE.match(doi)):
        raise ValueError(f"{path}:{line}: invalid DOI {doi!r}")
    if not isinstance(row["title"], str) or not row["title"].strip():
        raise ValueError(f"{path}:{line}: title required")
    if row["year"] is not None and (
        not isinstance(row["year"], int) or not 1600 <= row["year"] <= 2100
    ):
        raise ValueError(f"{path}:{line}: invalid year")
    if row["temporal_band"] not in TEMPORAL_BANDS:
        raise ValueError(f"{path}:{line}: invalid temporal_band")
    if row["access_status"] not in ACCESS:
        raise ValueError(f"{path}:{line}: invalid access_status")
    if row["metadata_status"] not in METADATA:
        raise ValueError(f"{path}:{line}: invalid metadata_status")
    if row["extraction_status"] not in EXTRACTION:
        raise ValueError(f"{path}:{line}: invalid extraction_status")
    if not isinstance(row["target_evidence_types"], list):
        raise ValueError(f"{path}:{line}: target_evidence_types must be a list")
    if not isinstance(row["discovered_via"], list) or not row["discovered_via"]:
        raise ValueError(f"{path}:{line}: discovered_via must be a non-empty list")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    parser.add_argument("--expected-benchmark-count", type=int, default=25)
    parser.add_argument("--queue", type=Path, action="append", default=[])
    args = parser.parse_args()

    benchmark = load_jsonl(args.benchmark)
    if len(benchmark) != args.expected_benchmark_count:
        raise ValueError(
            f"{args.benchmark}: expected {args.expected_benchmark_count} benchmark rows, got {len(benchmark)}"
        )
    for row in benchmark:
        validate_row(args.benchmark, row)
        if row["cohort"] != "benchmark" or row.get("hand_selected") is not True:
            raise ValueError(f"{args.benchmark}:{row['_line']}: benchmark row must be hand_selected")
        if row["metadata_status"] != "publisher_verified":
            raise ValueError(f"{args.benchmark}:{row['_line']}: gold benchmark metadata must be publisher_verified")

    all_rows = list(benchmark)
    for queue_path in args.queue:
        rows = load_jsonl(queue_path)
        for row in rows:
            validate_row(queue_path, row)
        all_rows.extend(rows)

    ids = [row["id"] for row in all_rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate acquisition candidate id")

    dois = [row["doi"].lower() for row in all_rows if row.get("doi")]
    if len(dois) != len(set(dois)):
        raise ValueError("Duplicate DOI across acquisition queues")

    bands: dict[str, int] = {}
    evidence: dict[str, int] = {}
    for row in benchmark:
        bands[row["temporal_band"]] = bands.get(row["temporal_band"], 0) + 1
        for evidence_type in row["target_evidence_types"]:
            evidence[evidence_type] = evidence.get(evidence_type, 0) + 1

    print(f"benchmark rows: {len(benchmark)}")
    print("temporal coverage:", json.dumps(dict(sorted(bands.items())), sort_keys=True))
    print("evidence coverage:", json.dumps(dict(sorted(evidence.items())), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
