#!/usr/bin/env python3
"""Compare the current build with a baseline build to prove the migration safe.

The baseline is a git revision whose committed ``public/data`` exports were
built by the previous model. The report checks, and fails loudly unless:

- every baseline publication is still present (no silent publication loss);
- every baseline opinion is still present as a claim;
- no opinion argues more strongly than before (the side a creature's rules put
  it on may only move towards neutral/usage, never away from it);
- every creature still exists.

Run after ``build_data.py``:

    python scripts/data/migration_report.py --baseline 9d29065 --out docs/audit/migration-report.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "build" / "fog-of-time.sqlite"
CREATURES = "public/data/theoretical/creatures.json"
MANIFEST = "public/data/manifest.json"
# How strongly a side argues; a migration may only move an opinion down.
SIDE_WEIGHT = {"usage": 0, "neutral": 0, "for": 1, "against": 1}
OLD_LIFE = {"proposes": "alive", "supports": None, "revives": "alive", "confirms": "confirmed", "challenges": "contested", "refutes": "dead"}


def git_json(revision: str, path: str) -> Any:
    return json.loads(subprocess.run(
        ["git", "show", f"{revision}:{path}"], cwd=ROOT, check=True, capture_output=True, text=True,
    ).stdout)


def old_final_state(events: list[dict[str, Any]]) -> str | None:
    state = None
    for event in events:
        if event["stance"] == "supports":
            state = "alive" if state == "contested" else state
        else:
            state = OLD_LIFE[event["stance"]]
    return state


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True, help="git revision holding the previous build's exports")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    baseline_sha = subprocess.run(["git", "rev-parse", args.baseline], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()
    old = git_json(baseline_sha, CREATURES)
    old_manifest = git_json(baseline_sha, MANIFEST)
    new = json.loads((ROOT / CREATURES).read_text(encoding="utf-8"))
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row

    problems: list[str] = []
    publications = {row[0] for row in connection.execute("SELECT id FROM publication")}
    claims = {row["id"]: row for row in connection.execute("SELECT * FROM taxonomic_opinion")}
    extraction_files = len(list((ROOT / "data" / "extracted").glob("*.json")))

    # Publications: the baseline export only lists cited ones; the manifest has the total.
    missing_publications = sorted(set(old["publications"]) - publications)
    if missing_publications:
        problems.append(f"publications lost: {missing_publications[:10]}")
    if len(publications) < old_manifest["publication_count"]:
        problems.append(f"publication count fell from {old_manifest['publication_count']} to {len(publications)}")
    if len(publications) != extraction_files:
        problems.append(f"{extraction_files} extraction files but {len(publications)} publications")

    # Opinions and sides, per creature. The old export has no opinion ids, so
    # opinions are matched by (creature, paper, summary) and derived ones by
    # (creature, paper, taxon) since their wording changed.
    new_creatures = {creature["id"]: creature for creature in new["creatures"]}
    transitions: dict[str, int] = {}
    strengthened: list[dict[str, Any]] = []
    unmatched = 0
    state_changes: list[dict[str, Any]] = []
    for creature in old["creatures"]:
        current = new_creatures.get(creature["id"])
        if current is None:
            problems.append(f"creature lost: {creature['id']}")
            continue
        new_by_paper: dict[str, list[dict[str, Any]]] = {}
        for paper in current["papers"]:
            new_by_paper.setdefault(paper["publication_id"], []).extend(paper["opinions"])
        for paper in creature["papers"]:
            for opinion in paper["opinions"]:
                candidates = new_by_paper.get(paper["publication_id"], [])
                match = next((item for item in candidates if item["summary"] == opinion["summary"]), None)
                if match is None and opinion["source"] == "derived_from_occurrence":
                    match = next((item for item in candidates if item["source"] == "derived_from_occurrence"
                                  and opinion["summary"].split(" of ", 1)[-1].split(" (")[0].split(";")[0].rstrip(".") == item["taxon"]), None)
                if match is None:
                    unmatched += 1
                    continue
                key = f"{opinion['side']}->{match['side']}"
                transitions[key] = transitions.get(key, 0) + 1
                # Arguing now where it did not, or for the other side.
                if SIDE_WEIGHT[match["side"]] and match["side"] != opinion["side"]:
                    strengthened.append({"creature": creature["id"], "publication": paper["publication_id"], "from": opinion["side"], "to": match["side"]})
        state_changes.append({
            "creature": creature["id"], "curated": creature["curated"],
            "before": old_final_state(creature["key_events"]),
            "after": current["states"][-1]["state"] if current["states"] else None,
        })
    if strengthened:
        problems.append(f"{len(strengthened)} opinions argue more strongly or switched sides: {strengthened[:5]}")
    if unmatched:
        problems.append(f"{unmatched} baseline opinions could not be matched to a claim")

    mapping = {"alive": "in_use", "confirmed": "in_use", "contested": "contested", "dead": "sunk"}
    changed = [item for item in state_changes if mapping.get(item["before"]) != item["after"]]
    old_stances: dict[str, int] = {}
    for creature in old["creatures"]:
        for event in creature["key_events"]:
            old_stances[event["stance"]] = old_stances.get(event["stance"], 0) + 1
    new_stances: dict[str, int] = {}
    for creature in new["creatures"]:
        for event in creature["key_events"]:
            new_stances[event["stance"]] = new_stances.get(event["stance"], 0) + 1

    report = {
        "schema_version": "fog-of-time.migration-report/v1",
        "baseline": baseline_sha,
        "publications": {"before": old_manifest["publication_count"], "after": len(publications), "extraction_files": extraction_files},
        "claims": {
            "baseline_opinions_in_creature_exports": sum(len(p["opinions"]) for c in old["creatures"] for p in c["papers"]),
            "claims_after": len(claims),
            "unmatched": unmatched,
        },
        "creatures": {"before": len(old["creatures"]), "after": len(new["creatures"])},
        "side_transitions": dict(sorted(transitions.items())),
        "strengthened": strengthened,
        "turning_points_by_stance": {"before": dict(sorted(old_stances.items())), "after": dict(sorted(new_stances.items()))},
        "final_state_changes": changed,
        "problems": problems,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("publications", "claims", "creatures", "side_transitions", "turning_points_by_stance")}, indent=2))
    print(f"{len(changed)} final states changed; {len(problems)} problems")
    for problem in problems:
        print(f"PROBLEM: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
