"""Regression tests for Fog of Time's scientific data model.

Run with:  python -m unittest discover -s tests -v
They build the real corpus into an in-memory database (no network).
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "data"))

import build_data  # noqa: E402
from claims import classify, strength_of  # noqa: E402
from history import automatic_key_events, derive_states, state_at  # noqa: E402
from publication_identity import compare, normalize_doi  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


def build() -> tuple[sqlite3.Connection, dict]:
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    built = build_data.build_database(connection)
    return connection, built


class PublicationIdentityTest(unittest.TestCase):
    fixture = json.loads((FIXTURES / "publication_identity.json").read_text(encoding="utf-8"))

    def test_doi_normalization(self):
        for case in self.fixture["doi"]:
            with self.subTest(raw=case["raw"]):
                result = normalize_doi(case["raw"])
                self.assertEqual(result.normalized, case["normalized"])
                self.assertEqual(result.status, case["status"])

    def test_pair_verdicts(self):
        for case in self.fixture["pairs"]:
            with self.subTest(case=case["case"]):
                self.assertEqual(compare(case["a"], case["b"]).verdict, case["verdict"])
                # Identity is symmetric.
                self.assertEqual(compare(case["b"], case["a"]).verdict, case["verdict"])

    def test_only_same_may_merge(self):
        for case in self.fixture["pairs"]:
            verdict = compare(case["a"], case["b"])
            self.assertEqual(verdict.may_merge, verdict.verdict == "same")


class ClaimSemanticsTest(unittest.TestCase):
    def test_usage_is_never_an_argument(self):
        derived = {"id": "x", "taxon": "Stygimoloch", "status": "identified_as", "basis": "stated with evidence", "source": "derived_from_occurrence"}
        self.assertEqual(strength_of(derived), "usage")
        self.assertEqual(classify(derived)["assertion"], "uses_name")

    def test_strength_never_exceeds_recorded_basis(self):
        base = {"id": "pbdb-opinion:1", "taxon": "Nanotyrannus", "status": "subjective_synonym_of", "source": "pbdb_opinion"}
        self.assertEqual(strength_of({**base, "basis": "implied"}), "implied")
        self.assertEqual(strength_of({**base, "basis": "stated without evidence"}), "stated")
        self.assertEqual(strength_of({**base, "basis": "stated with evidence"}), "argued")
        # A direct reading with no recorded basis is not promoted to "argued".
        self.assertEqual(strength_of({**base, "id": "y", "source": "full_text", "basis": None}), "stated")

    def test_other_genus_is_not_support_for_the_tracked_genus(self):
        opinion = {"id": "pbdb-opinion:79134", "taxon": "Nanotyrannus lancensis", "published_as": "Gorgosaurus lancensis",
                   "status": "belongs_to", "related_taxon": "Gorgosaurus", "basis": "stated without evidence", "source": "pbdb_opinion"}
        claim = classify(opinion)
        self.assertEqual(claim["assertion"], "places_in_other_genus")
        self.assertEqual(claim["name_as_published"], "Gorgosaurus lancensis")


class HistoryRuleTest(unittest.TestCase):
    def claim(self, index, year, side, strength):
        return {"id": f"c{index}", "publication_id": f"p{index}", "year": year, "side": side, "strength": strength}

    def test_usage_alone_never_moves_state(self):
        claims = [self.claim(0, 1900, "for", "stated"), self.claim(1, 1901, "against", "stated")]
        claims += [self.claim(i, 1901 + i, "usage", "usage") for i in range(2, 12)]
        events = automatic_key_events(claims)
        self.assertEqual([event["stance"] for event in events], ["proposes", "challenges"])
        self.assertEqual(derive_states(events, claims)[-1]["state"], "contested")

    def test_one_stated_claim_does_not_sink(self):
        claims = [self.claim(0, 1900, "for", "stated"), self.claim(1, 1950, "against", "stated")]
        self.assertEqual([event["stance"] for event in automatic_key_events(claims)], ["proposes", "challenges"])

    def test_states_never_use_later_claims(self):
        claims = [self.claim(0, 1900, "for", "stated"), self.claim(1, 1950, "against", "argued"), self.claim(2, 2000, "for", "argued")]
        events = automatic_key_events(claims)
        changes = derive_states(events, claims)
        self.assertEqual(state_at(changes, 1949)["state"], "in_use")
        self.assertEqual(state_at(changes, 1950)["state"], "sunk")
        self.assertEqual(state_at(changes, 2000)["state"], "in_use")
        # Replaying only the claims up to 1960 gives the same answer for 1960.
        early = [claim for claim in claims if claim["year"] <= 1960]
        self.assertEqual(state_at(derive_states(automatic_key_events(early), early), 1960), state_at(changes, 1960))


class CorpusTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.connection, cls.built = build()
        cls.connection.row_factory = sqlite3.Row
        cls.export = build_data.export_creatures(cls.connection, cls.built["creatures"] + cls.built["official"])
        cls.creatures = {creature["id"]: creature for creature in cls.export["creatures"]}

    def scalar(self, sql, *args):
        return self.connection.execute(sql, args).fetchone()[0]

    def test_no_silent_publication_loss(self):
        files = len(list((ROOT / "data" / "extracted").glob("*.json")))
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM publication"), files)

    def test_zero_orphan_references(self):
        self.assertEqual(self.connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_no_unmerged_duplicates(self):
        self.assertEqual([pair for pair in self.built["identity"]["pairs"] if pair["verdict"] == "same"], [])

    def test_merged_pbdb_references_stay_traceable(self):
        manifest = json.loads(build_data.OPINION_IMPORT_MANIFEST.read_text(encoding="utf-8"))
        for reference in manifest["references"]:
            self.assertEqual(self.scalar(
                "SELECT COUNT(*) FROM publication_identifier WHERE scheme = 'pbdb_reference' AND value = ?", str(reference["reference_id"])
            ), 1, reference)

    def test_usage_never_argues(self):
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM taxonomic_opinion WHERE status = 'identified_as' AND strength <> 'usage'"), 0)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM taxonomic_opinion WHERE source = 'derived_from_occurrence' AND related_taxon IS NOT NULL"), 0)
        for creature in self.export["creatures"]:
            for paper in creature["papers"]:
                for claim in paper["opinions"]:
                    if claim["strength"] == "usage":
                        self.assertEqual(claim["side"], "usage", (creature["id"], claim["id"]))
            for event in creature["key_events"]:
                if event["opinion"]["strength"] == "usage":
                    self.assertEqual(event["stance"], "recorded", creature["id"])

    def test_every_derived_state_is_traceable(self):
        for creature in self.export["creatures"]:
            self.assertTrue(creature["turning_points"], creature["id"])
            self.assertTrue(creature["states"], creature["id"])
            claims = {claim["id"] for paper in creature["papers"] for claim in paper["opinions"]}
            for change in creature["states"]:
                self.assertIn(change["opinion_id"], claims, creature["id"])
                self.assertIn(change["publication_id"], self.export["publications"])
            for paper in creature["papers"]:
                for claim in paper["opinions"]:
                    self.assertTrue(claim["source_records"], claim["id"])
                    if claim["authority"] == "build_derived":
                        self.assertTrue(claim["derivation_rule"], claim["id"])

    def test_historical_names_survive(self):
        # A fossil the paper reported under one name keeps it next to PBDB's current name.
        renamed = self.scalar(
            "SELECT COUNT(*) FROM publication_evidence r JOIN taxon t ON t.id = r.taxon_id WHERE r.taxon_as_published <> t.name"
        )
        self.assertGreater(renamed, 0)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM taxonomic_opinion WHERE name_as_published IS NULL OR name_as_published = ''"), 0)

    def test_case_studies(self):
        fixture = json.loads((FIXTURES / "case_studies.json").read_text(encoding="utf-8"))
        for case in fixture["cases"]:
            creature = self.creatures[case["creature"]]
            with self.subTest(creature=case["creature"]):
                for year, expected in case["states"].items():
                    change = state_at(creature["states"], int(year))
                    self.assertEqual(change["state"] if change else None, expected, f"{case['creature']} in {year}")
                for year, names in case.get("published_as", {}).items():
                    used = {claim["name_as_published"] for paper in creature["papers"]
                            if self.export["publications"][paper["publication_id"]]["year"] <= int(year) for claim in paper["opinions"]}
                    for name in names:
                        self.assertIn(name, used, f"{case['creature']} by {year}")
                for year, names in case.get("not_published_as_by", {}).items():
                    used = {claim["name_as_published"] for paper in creature["papers"]
                            if self.export["publications"][paper["publication_id"]]["year"] <= int(year) for claim in paper["opinions"]}
                    for name in names:
                        self.assertNotIn(name, used, f"{case['creature']} by {year}")
                for stance, strengths in case.get("turning_point_opinion_strengths", {}).items():
                    for event in creature["key_events"]:
                        if event["stance"] == stance:
                            self.assertIn(event["opinion"]["strength"], strengths)
                if "sunk_by_authority" in case:
                    self.assertEqual(creature["key_events"][-1]["opinion"]["authority"], case["sunk_by_authority"])
                if "turning_points" in case:
                    self.assertEqual(len(creature["key_events"]), case["turning_points"])

    def test_no_adjudicating_stance(self):
        stances = {row[0] for row in self.connection.execute("SELECT DISTINCT stance FROM hypothesis_event")}
        self.assertNotIn("confirms", stances)

    def test_curated_turning_points_meet_their_floor_or_explain(self):
        rows = self.connection.execute(
            """SELECT e.stance, o.strength, e.rationale FROM hypothesis_event e JOIN taxonomic_opinion o ON o.id = e.opinion_id
               JOIN theoretical_creature t ON t.id = e.creature_id WHERE t.curated = 1"""
        ).fetchall()
        rank = {"usage": 0, "implied": 1, "stated": 2, "argued": 3}
        floor = {"proposes": 1, "supports": 2, "challenges": 2, "refutes": 3, "revives": 3}
        for row in rows:
            self.assertTrue(rank[row["strength"]] >= floor[row["stance"]] or row["rationale"], tuple(row))


class ValidationTest(unittest.TestCase):
    def creature(self, **overrides):
        document = {
            "schema_version": build_data.CREATURE_SCHEMA_VERSION, "id": "x", "name": "X", "hypothesis": "X is real.",
            "taxa": ["X"], "rules": {"for": [{"status": ["belongs_to"]}]},
            "key_events": [{"publication_id": "p", "stance": "proposes"}],
        }
        document.update(overrides)
        return document

    def test_rules_may_not_count_usage(self):
        with self.assertRaisesRegex(ValueError, "name usage"):
            build_data.validate_creature(self.creature(rules={"for": [{"status": ["identified_as"]}]}), ROOT / "x.json")

    def test_confirms_is_gone(self):
        events = [{"publication_id": "p", "stance": "proposes"}, {"publication_id": "q", "stance": "confirms"}]
        with self.assertRaisesRegex(ValueError, "unknown stance"):
            build_data.validate_creature(self.creature(key_events=events), ROOT / "x.json")


if __name__ == "__main__":
    unittest.main()
