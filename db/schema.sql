PRAGMA foreign_keys = ON;

CREATE TABLE publication (
  id TEXT PRIMARY KEY,
  -- Normalized DOI (publication_identity.normalize_doi). Unique: two records
  -- with one DOI are one work and must be merged before the build.
  doi TEXT UNIQUE,
  -- The DOI exactly as the source gave it, and whether it was used as is,
  -- cosmetically repaired, or is invalid (kept, never used for identity).
  doi_raw TEXT,
  doi_status TEXT NOT NULL DEFAULT 'ok' CHECK (doi_status IN ('ok', 'repaired', 'invalid')),
  title TEXT NOT NULL,
  year INTEGER NOT NULL,
  month INTEGER CHECK (month BETWEEN 1 AND 12),
  journal TEXT,
  url TEXT,
  development_fixture INTEGER NOT NULL DEFAULT 0 CHECK (development_fixture IN (0, 1))
);

-- Every identifier known for a publication, with where it came from. A PBDB
-- reference merged into another record (same DOI and title) keeps its number here.
CREATE TABLE publication_identifier (
  publication_id TEXT NOT NULL REFERENCES publication(id),
  scheme TEXT NOT NULL CHECK (scheme IN ('doi', 'pbdb_reference', 'record_id')),
  value TEXT NOT NULL,
  provenance TEXT NOT NULL,
  PRIMARY KEY (scheme, value)
);

-- Pairs of records the identity rules did not call distinct (probable
-- duplicates, related notices, identifier conflicts). Never merged silently.
CREATE TABLE publication_identity_issue (
  publication_a TEXT NOT NULL REFERENCES publication(id),
  publication_b TEXT NOT NULL REFERENCES publication(id),
  verdict TEXT NOT NULL,
  rule TEXT NOT NULL,
  detail TEXT,
  PRIMARY KEY (publication_a, publication_b)
);

CREATE TABLE author (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE
);

CREATE TABLE publication_author (
  publication_id TEXT NOT NULL REFERENCES publication(id) ON DELETE CASCADE,
  author_id INTEGER NOT NULL REFERENCES author(id),
  author_order INTEGER NOT NULL,
  PRIMARY KEY (publication_id, author_id)
);

CREATE TABLE taxon (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  rank TEXT
);

CREATE TABLE specimen (
  id TEXT PRIMARY KEY,
  institution_code TEXT,
  catalog_number TEXT,
  label TEXT
);

CREATE TABLE physical_evidence (
  physical_key TEXT PRIMARY KEY,
  evidence_type TEXT NOT NULL,
  specimen_id TEXT REFERENCES specimen(id)
);

CREATE TABLE locality (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  country TEXT NOT NULL,
  region TEXT,
  latitude REAL,
  longitude REAL,
  coordinate_uncertainty_km REAL
);

CREATE TABLE formation (
  id TEXT PRIMARY KEY,
  name TEXT,
  member_name TEXT,
  group_name TEXT
);

CREATE TABLE publication_evidence (
  id TEXT PRIMARY KEY,
  publication_id TEXT NOT NULL REFERENCES publication(id),
  physical_key TEXT NOT NULL REFERENCES physical_evidence(physical_key),
  taxon_id TEXT NOT NULL REFERENCES taxon(id),
  -- The name the publication itself used, and what taxon_id's name is: the
  -- name as published, or a later database's accepted name for the material.
  taxon_as_published TEXT NOT NULL,
  taxon_name_basis TEXT NOT NULL CHECK (taxon_name_basis IN ('as_published', 'pbdb_accepted_name')),
  locality_id TEXT NOT NULL REFERENCES locality(id),
  formation_id TEXT REFERENCES formation(id),
  evidence_role TEXT NOT NULL,
  age_min_ma REAL NOT NULL,
  age_max_ma REAL NOT NULL,
  age_best_ma REAL,
  age_precision TEXT NOT NULL,
  dating_method TEXT NOT NULL,
  age_basis TEXT,
  age_notes TEXT,
  development_fixture INTEGER NOT NULL DEFAULT 0 CHECK (development_fixture IN (0, 1)),
  CHECK (age_min_ma <= age_max_ma),
  CHECK (age_best_ma IS NULL OR (age_best_ma >= age_min_ma AND age_best_ma <= age_max_ma))
);

CREATE TABLE material (
  publication_evidence_id TEXT NOT NULL REFERENCES publication_evidence(id) ON DELETE CASCADE,
  material TEXT NOT NULL,
  PRIMARY KEY (publication_evidence_id, material)
);

CREATE TABLE claim (
  id TEXT PRIMARY KEY,
  publication_evidence_id TEXT NOT NULL REFERENCES publication_evidence(id) ON DELETE CASCADE,
  claim_type TEXT NOT NULL,
  summary TEXT NOT NULL,
  page TEXT,
  figure TEXT,
  table_ref TEXT
);

CREATE INDEX idx_publication_evidence_age ON publication_evidence(age_min_ma, age_max_ma);
CREATE INDEX idx_publication_evidence_taxon ON publication_evidence(taxon_id);
CREATE INDEX idx_publication_evidence_physical ON publication_evidence(physical_key);

-- One paper's claim about a name: it belongs to a parent, is a synonym, is a
-- nomen dubium, and so on. Most come from PBDB opinions; "identified_as" rows
-- are derived from a paper's own fossil identifications and are name usage
-- only. The claim columns are derived by scripts/data/claims.py.
CREATE TABLE taxonomic_opinion (
  id TEXT PRIMARY KEY,
  publication_id TEXT NOT NULL REFERENCES publication(id),
  -- The tracked (normalized) name: PBDB's current label for the taxon concept.
  taxon_name TEXT NOT NULL,
  -- The spelling/combination the source recorded, when it differs.
  published_as TEXT,
  -- Always the literal historical name the paper used.
  name_as_published TEXT NOT NULL,
  status TEXT NOT NULL,
  -- The claim's target, as the source recorded it.
  related_taxon TEXT,
  basis TEXT,
  summary TEXT NOT NULL,
  source TEXT NOT NULL,
  assertion TEXT NOT NULL,
  strength TEXT NOT NULL CHECK (strength IN ('usage', 'implied', 'stated', 'argued')),
  authority TEXT NOT NULL CHECK (authority IN ('pbdb_compiled', 'direct_full_text', 'direct_abstract_unverified', 'build_derived')),
  -- Rule that produced a build-derived claim, and the upstream records it rests on.
  derivation_rule TEXT,
  source_records TEXT NOT NULL,
  -- For derived usage only: the name a later database files the material
  -- under. Not part of the paper's claim.
  current_name TEXT,
  -- A specimen the claim is about, when it is about one specimen rather than a name.
  subject_specimen TEXT,
  CHECK (source <> 'derived_from_occurrence' OR (strength = 'usage' AND derivation_rule IS NOT NULL))
);

CREATE INDEX idx_taxonomic_opinion_taxon ON taxonomic_opinion(taxon_name);

-- Theoretical creatures: a hypothesised animal whose "life" is the life of the
-- hypothesis, argued over in the opinions of ingested papers.
CREATE TABLE theoretical_creature (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  scientific_name TEXT,
  hypothesis TEXT NOT NULL,
  -- Where the turning points come from: a curated file or a versioned rule.
  turning_points TEXT NOT NULL,
  -- 1 for a hand-curated theoretical creature; 0 for an official creature
  -- whose life follows the automatic rule in build_data.py.
  curated INTEGER NOT NULL DEFAULT 1 CHECK (curated IN (0, 1))
);

CREATE TABLE creature_taxon (
  creature_id TEXT NOT NULL REFERENCES theoretical_creature(id) ON DELETE CASCADE,
  taxon_name TEXT NOT NULL,
  PRIMARY KEY (creature_id, taxon_name)
);

-- The moments that change a hypothesis's life, each resting on one opinion.
CREATE TABLE hypothesis_event (
  creature_id TEXT NOT NULL REFERENCES theoretical_creature(id) ON DELETE CASCADE,
  publication_id TEXT NOT NULL REFERENCES publication(id),
  opinion_id TEXT NOT NULL REFERENCES taxonomic_opinion(id),
  stance TEXT NOT NULL CHECK (stance IN ('proposes', 'recorded', 'supports', 'challenges', 'refutes', 'revives')),
  event_order INTEGER NOT NULL,
  -- A curator's reason, required when a curated turning point rests on a
  -- claim weaker than the stance normally needs.
  rationale TEXT,
  PRIMARY KEY (creature_id, event_order)
);

-- Derived corpus state of each hypothesis over publication time (history.py).
-- A view over the claims, never scientific authority: each row names the
-- turning point or opposing claim that caused it.
CREATE TABLE creature_state (
  creature_id TEXT NOT NULL REFERENCES theoretical_creature(id) ON DELETE CASCADE,
  sequence INTEGER NOT NULL,
  year INTEGER NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('in_use', 'contested', 'sunk')),
  cause_kind TEXT NOT NULL CHECK (cause_kind IN ('turning_point', 'opposing_claim')),
  opinion_id TEXT NOT NULL REFERENCES taxonomic_opinion(id),
  publication_id TEXT NOT NULL REFERENCES publication(id),
  rule TEXT NOT NULL,
  PRIMARY KEY (creature_id, sequence)
);
