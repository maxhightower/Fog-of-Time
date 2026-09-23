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
  theoretical/         hypothesised creatures, built from ingested papers' opinions
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
  theoretical/creatures.json

src/
  main.ts               page shell, layers panel, filters, detail view
  timeline.ts           SVG timeline (bars, geologic bands, pan/zoom)
  model.ts              grouping, colour categories
  timescale.ts          ICS geologic time scale reference bands
  creatures.ts          theoretical creature lifelines
```

## Run the website

```bash
npm install
npm run dev
```

### The timeline

A **Time axis** switch changes the horizontal axis between the estimated geologic age
(Ma) and the publication date of each record's paper, where each record is a point at
its paper's publication month. Each axis keeps its own window.

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

The committed production dataset now combines a 25-paper direct-full-text benchmark with a separate PBDB occurrence-backed scale-out tier. Development fixtures remain only under `tests/fixtures/` and never enter the production timeline.

### Theoretical creatures

Below the fossil timeline, **Theoretical creatures** tracks animals that started life as
hypotheses, such as the American cheetah (*Miracinonyx*), Nanotyrannus, Brontosaurus and
"Toroceratops". Every creature is built from ingested papers, specifically the
taxonomic opinions they hold. Each row is a lifeline across publication years: born when a paper
proposes the animal, contested, killed by a refutation, and sometimes revived, with a
small tick for every other ingested paper that argued the point. The "Known by" slider
replays these lives too. A side panel lists every creature with its status and number
of ingested papers (for ▲ / against ▼); click one for its full cited history. See
[docs/DATA_MODEL.md](docs/DATA_MODEL.md#theoretical-creatures) to add one.

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

## DINO-2 scale-out

Two PBDB-backed scale-out batches add **200 publications** and **571 fossil occurrence records** while keeping provenance explicit. These database-derived records are marked `secondary_citation`; they do not masquerade as direct full-text extraction.

The current DINO-3 snapshot contains **225 publications and 727 physical evidence objects** in total.

See `data/acquisition/README.md` for both acquisition tiers and the import workflow.
