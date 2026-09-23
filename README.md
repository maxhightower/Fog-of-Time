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

### Notebook sections

The page is organised like a notebook, with coloured section tabs along the top:

- **Deep time** shows the fossil timeline on the estimated geologic age axis (Ma).
- **Publication date** shows the same records, each a point at its paper's publication month.
- **Creatures** shows every creature's life in the literature (see below).

The two timeline sections share filters and layers, and each keeps its own window. The
URL hash (`#deep-time`, `#publication-date`, `#creatures`) remembers the open section,
and the arrow keys move between tabs. **Esc** clears every selection on the page:
timeline bars and groups, the selected creature, open menus and tooltips.

### The timeline

The default view spans 500 million years ago to today. Presets, From/To inputs,
zoom buttons, drag-to-pan and Ctrl/⌘-scroll adjust the window.

Every record is drawn as a bar across its full age interval, never collapsed to a
midpoint. Bar shape encodes how the date is known (hard-edged explicit range,
feathered stage-derived interval, glowing approximate point, crisp reported point).
Records can be grouped by paper, taxon, evidence type, dating basis or country (or
shown individually); clicking a group expands its records. They can be coloured by
evidence type, dating basis, or **taxon or name**. With taxon or name, up to three names
(anything the name filter accepts, such as "T. rex" or "Sue") each keep a colour and
everything else is "Other names".

Geologic time scale bands (periods, epochs, Mesozoic stages) run along the top of the
timeline. The **Layers** panel sets grouping, colour and data labels (with a choice of
what group bars and record bars show), and a "Known by" slider replays the evidence
by publication year.

The committed production dataset now combines a 25-paper direct-full-text benchmark with a separate PBDB occurrence-backed scale-out tier. Development fixtures remain only under `tests/fixtures/` and never enter the production timeline.

### Creatures

The **Creatures** section tracks every creature as a hypothesis argued over in the
ingested papers. That covers every genus and species the corpus reports fossils of (the
**official** creatures) and hand-curated **theoretical** creatures that started life as
hypotheses, such as the American cheetah (*Miracinonyx*), Nanotyrannus and
"Toroceratops". Each lifeline runs across publication years: born when a paper proposes
the animal, contested, killed by a refutation, and sometimes revived, with a small tick
for every other ingested paper that argued the point. The list can be searched,
filtered (theoretical, official, contested, dead) and sorted, and it has its own "Known
by" replay. Official creatures' turning points follow one written-down rule; theoretical
ones are curated. See [docs/DATA_MODEL.md](docs/DATA_MODEL.md#theoretical-creatures).

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
