# Dinosaur literature acquisition

This directory sits **upstream** of the canonical evidence database.

A row here means *Fog of Time knows a paper exists and may want to extract it*.
It does **not** mean the paper's fossil evidence has been admitted to SQLite.

## Queues

- `benchmark.jsonl` — 25 hand-selected, publisher-verified, open-access papers used as the gold extraction corpus.
- `candidates.crossref.jsonl` — generated discovery candidates; not committed until reviewed.
- `discovery_queries.json` — broad search vocabulary for the first Crossref discovery adapter.

The 25-paper benchmark intentionally covers Triassic through Late Cretaceous
records and several evidence classes: body fossils, trackways/traces, eggs/nests,
histology, pathology, feathers/skin and soft tissue.

## Status boundary

```text
discovered
   ↓
metadata resolved
   ↓
access checked
   ↓
extraction pending
   ↓
data/extracted/<paper>.json
   ↓
reviewed / admitted
   ↓
SQLite
```

No acquisition candidate becomes a timeline point merely because its title,
abstract or bibliographic metadata mentions a dinosaur.

## Discover more papers

Crossref is the first automated discovery adapter:

```bash
python scripts/data/acquisition/discover_crossref.py --mailto you@example.com
```

Crossref recommends identifying API clients with an email address; this can also
be supplied as `CROSSREF_MAILTO`.

The output is written to:

```text
data/acquisition/candidates.crossref.jsonl
```

The script excludes benchmark DOIs, deduplicates by DOI, preserves which queries
matched each work, and ranks by Crossref's search score. It does not download
papers or modify the evidence database.

## Validate queues

```bash
python scripts/data/acquisition/validate_queue.py
```

CI runs this validator without network access.

## PBDB scale-out ingestion

The 25-paper benchmark is the high-confidence direct-full-text tier. Larger coverage can be
snapshotted from Paleobiology Database without weakening that distinction:

```bash
python scripts/data/acquisition/import_pbdb_references.py --paper-count 100
```

The importer selects 100 additional PBDB references linked to Mesozoic dinosaur
occurrences, excludes titles/DOIs already represented by direct extraction, and writes:

```text
data/extracted/pbdb-ref-*.json
data/acquisition/pbdb-import-manifest.json
```

Each PBDB-derived record is a `fossil_occurrence`, not a museum specimen claim.
It retains the PBDB occurrence number, collection/locality, accepted taxon, stratigraphy,
numerical age range, and publication reference. These records use
`evidence_role: secondary_citation` until direct publication review upgrades them.

The first DINO-2 snapshot contains **100 additional publications and 268 PBDB
occurrences**. DINO-3 appends a second non-overlapping batch of **100 publications
and 303 PBDB occurrences**, recorded in
`data/acquisition/pbdb-import-manifest-batch-2.json`.

PBDB imports are append-safe by default: existing direct and PBDB publication
titles/DOIs are excluded, and existing `pbdb-ref-*.json` records are preserved.
Use `--replace-existing-pbdb` only when deliberately rebuilding the entire PBDB
snapshot.

## Paper bytes

Fog of Time does not need to commit full paper PDFs. Full text may be acquired
transiently for extraction when licensing/access permits; the durable repository
artifact is the compact provenance-bearing extraction JSON.

## PBDB taxonomic opinions (theoretical creatures)

Creatures are built from the taxonomic opinions held by ingested papers. That covers the
curated theoretical creatures in `data/theoretical/*.json` and every genus and species
the corpus reports fossils of. To ingest the papers behind them:

```bash
python scripts/data/acquisition/import_pbdb_opinions.py
```

For every taxon a creature tracks, this snapshots PBDB's opinions and keeps the primary
ones, where the opinion's author and year match its reference. PBDB's "unpublished"
references (compilers' own opinion lists) are skipped. A reference that repeats an
ingested paper's DOI and title merges into that paper. It then merges them into
the existing extraction record for that paper, or writes an opinion-only record. The
snapshot is logged in `data/acquisition/pbdb-opinion-import-manifest.json`. Occurrence
re-imports with `--replace-existing-pbdb` keep records that carry opinions.
