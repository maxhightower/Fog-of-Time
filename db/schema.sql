PRAGMA foreign_keys = ON;

CREATE TABLE publication (
  id TEXT PRIMARY KEY,
  doi TEXT UNIQUE,
  title TEXT NOT NULL,
  year INTEGER NOT NULL,
  month INTEGER CHECK (month BETWEEN 1 AND 12),
  journal TEXT,
  url TEXT,
  development_fixture INTEGER NOT NULL DEFAULT 0 CHECK (development_fixture IN (0, 1))
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

-- One paper's verdict on a name: it belongs to a parent, is a synonym, is a
-- nomen dubium, and so on. Most come from PBDB opinions; "identified_as" rows
-- are derived from a paper's own fossil identifications.
CREATE TABLE taxonomic_opinion (
  id TEXT PRIMARY KEY,
  publication_id TEXT NOT NULL REFERENCES publication(id),
  taxon_name TEXT NOT NULL,
  published_as TEXT,
  status TEXT NOT NULL,
  related_taxon TEXT,
  basis TEXT,
  summary TEXT NOT NULL,
  source TEXT NOT NULL
);

CREATE INDEX idx_taxonomic_opinion_taxon ON taxonomic_opinion(taxon_name);

-- Theoretical creatures: a hypothesised animal whose "life" is the life of the
-- hypothesis, argued over in the opinions of ingested papers.
CREATE TABLE theoretical_creature (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  scientific_name TEXT,
  hypothesis TEXT NOT NULL,
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
  stance TEXT NOT NULL CHECK (stance IN ('proposes', 'supports', 'challenges', 'refutes', 'revives', 'confirms')),
  event_order INTEGER NOT NULL,
  PRIMARY KEY (creature_id, event_order)
);
