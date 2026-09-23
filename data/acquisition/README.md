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

## Paper bytes

Fog of Time does not need to commit full paper PDFs. Full text may be acquired
transiently for extraction when licensing/access permits; the durable repository
artifact is the compact provenance-bearing extraction JSON.
