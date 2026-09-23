PRAGMA foreign_keys = ON;

CREATE TABLE publication (
  id TEXT PRIMARY KEY,
  doi TEXT UNIQUE,
  title TEXT NOT NULL,
  year INTEGER NOT NULL,
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
