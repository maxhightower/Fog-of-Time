# Fog of Time

Fog of Time is an evidence-first explorer of the dinosaur fossil record.

The first milestone is deliberately narrow: paper metadata and the physical evidence those papers report, rendered on an interactive deep-time timeline with explicit age uncertainty and provenance.

## Architecture

```text
checked-in paper extraction JSON
            |
            v
  offline normalization build
      |               |
      v               v
SQLite truth     static web artifacts
                      |
                      v
                   Vite UI
```

The browser never queries PBDB, Crossref, OpenAlex, publisher sites, or other scientific services. Acquisition and extraction happen before the frontend build.

### Important identity rule

**A paper is not a fossil.**

A stable `physical_key` identifies the actual specimen, trace, tracksite, or other physical evidence. Papers attach separate `publication_evidence` reports to that key. Ten papers discussing one specimen therefore remain one physical evidence object with ten reports.

See [docs/DATA_MODEL.md](docs/DATA_MODEL.md).

## Repository layout

```text
data/
  extracted/           reviewable paper extraction records
  schema/              extraction contract

db/
  schema.sql            normalized SQLite schema

scripts/data/
  build_data.py         offline validator + SQLite/static exporter

build/
  fog-of-time.sqlite    generated locally; not committed

public/data/
  manifest.json
  timeline/all.json     generated browser artifacts

src/
  main.ts               Vite client
```

## Run the website

```bash
npm install
npm run dev
```

The repository currently commits a tiny **development-fixture dataset** so the frontend works immediately. The UI labels it clearly as non-scientific fixture data.

## Rebuild data

Python 3 is only required for the offline data build:

```bash
python scripts/data/build_data.py
```

This validates every `data/extracted/*.json`, rebuilds `build/fog-of-time.sqlite`, and rewrites the static files in `public/data/`. It performs no network access.

## Production evidence standard

Every production timeline point must be traceable:

```text
timeline point
  -> physical evidence
  -> publication report
  -> age assertion
  -> publication
  -> page / figure / table when available
```

If a displayed fact cannot retain that provenance chain, it does not enter the production dataset.

## DINO-1 acquisition

The first 25-paper hand-selected benchmark lives in `data/acquisition/benchmark.jsonl`.
Automated Crossref discovery is available via `scripts/data/acquisition/discover_crossref.py`.

The production evidence corpus has begun with publisher-verified extraction records under
`data/extracted/`. Development fixtures live under `tests/fixtures/extracted/` and are
not part of the production timeline.

See `data/acquisition/README.md` for the acquisition workflow.
