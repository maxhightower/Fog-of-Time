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
  main.ts               page shell, layers panel, filters, detail view
  timeline.ts           SVG timeline (bars, geologic bands, pan/zoom)
  model.ts              grouping, colour categories
  timescale.ts          ICS geologic time scale reference bands
```

## Run the website

```bash
npm install
npm run dev
```

### The timeline

A **Time axis** switch changes the horizontal axis between the estimated geologic age
(Ma) and the publication year of each record's paper. Each axis keeps its own window.

The default view spans 500 million years ago to today. Presets, From/To inputs,
zoom buttons, drag-to-pan and Ctrl/⌘-scroll adjust the window.

Every record is drawn as a bar across its full age interval, never collapsed to a
midpoint. Bar shape encodes how the date is known (hard-edged explicit range,
feathered stage-derived interval, glowing approximate point, crisp reported point).
Records can be grouped by paper, taxon, evidence type, dating basis or country (or
shown individually); clicking a group expands its records.

Geologic time scale bands (periods, epochs, Mesozoic stages) run along the top of the
timeline. The **Layers** panel sets grouping, colour and data labels (with a choice of
what group bars and record bars show), and a "Known by" slider replays the evidence
by publication year.

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
