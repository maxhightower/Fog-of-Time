# Fog of Time data model

## Core rule

A paper is provenance, not a fossil.

Fog of Time separates a stable physical evidence identity from each paper's report about that evidence:

```text
physical_evidence
      |
      +-- specimen
      |
      +-- publication_evidence -- publication
                    |
                    +-- taxon assignment
                    +-- locality / stratigraphy
                    +-- age assertion
                    +-- material
                    +-- claims
```

The same specimen may therefore accumulate many publication reports without becoming many timeline fossils.

## Stable physical keys

Every extraction record supplies a `physical_key`. Examples of intended production forms are:

- `specimen:fmnh:pr-2081`
- `specimen:bhi:3033`
- `tracksite:institution-or-locality:catalog-or-stable-slug`

A physical key must identify the evidence object or site, not the paper discussing it.

## Time convention

All ages are millions of years before present (Ma).

- `min_ma` is the younger numerical boundary.
- `max_ma` is the older numerical boundary.
- `best_ma` is optional and must fall inside the interval.
- `precision` distinguishes an explicit range, an approximate range, a reported point, an approximate point, a derived interval, or unknown precision.
- the dating method and basis remain attached to the publication report.

A paper that says “ca. 228.3 Ma” therefore remains an approximate point even when no numerical error term is supplied. The UI must display uncertainty rather than silently replacing an interval with its midpoint or an approximate age with fake exactness.

## Provenance

Claims retain compact source locators (page, figure, table when available). Fog of Time does not need to store full copyrighted papers in the repository.

Fog of Time currently has two explicit provenance tiers:

- **Direct full-text extraction** — the 25-paper benchmark was read against the publication and stores specimen/trace-level details directly from the paper and supplements.
- **PBDB occurrence-backed extraction** — scale-out records use Paleobiology Database occurrence and reference records. These are stored as `fossil_occurrence` with `evidence_role: secondary_citation`, and their age notes state that they have not yet been re-verified against publication full text.

Database-backed occurrence records use stable keys such as `pbdb-occ:130209`. They represent a PBDB taxon occurrence at a collection, not a claim that PBDB exposed an individual catalogued museum specimen.

## Canonical and delivery formats

Checked-in extraction JSON is the reviewable source record. The offline build normalizes those records into `build/fog-of-time.sqlite`. The Vite client does not read SQLite and does not contact scientific APIs; it loads generated artifacts under `public/data/`.

## Representative report policy

The first web exporter uses `latest-publication-report-v0` only as a display policy when multiple papers refer to the same physical key. The database retains all reports. This policy is intentionally explicit and replaceable rather than pretending the newest paper is automatically correct.

## Taxonomic opinions

Besides physical evidence, an extraction record may carry `opinions`: the paper's own verdicts on names. Each opinion says that a taxon belongs to a parent, is a synonym of another, is a nomen dubium, and so on (`taxon`, `status`, `related_taxon`, `basis`, `summary`, `source`). A paper must contribute evidence, opinions or both.

- **PBDB opinions** (`source: pbdb_opinion`) are snapshotted by `scripts/data/acquisition/import_pbdb_opinions.py`. Only *primary* opinions are kept, meaning the opinion's author and year match the reference it is recorded from. Papers already in the corpus get opinions merged in; others are ingested as opinion-only records.
- **Direct extraction** (`source: full_text` or `abstract`) records an opinion read from the paper itself. `abstract` marks an abstract-level reading that has not yet been verified against the full text.
- **Derived opinions** (`source: derived_from_occurrence`) are created by the build. A paper that identified its fossils under a name the accepted taxonomy has since replaced is recorded as using that name (`status: identified_as`).

Opinions are stored in the `taxonomic_opinion` table.

## Theoretical creatures

Some animals are first known as hypotheses. The "American cheetah" was a proposed North American cheetah until ancient DNA showed *Miracinonyx* was a puma relative. Fog of Time tracks these as **theoretical creatures** in `data/theoretical/*.json` (schema: `data/schema/theoretical-creature.schema.json`). Everything shown for a creature comes from ingested papers:

- `taxa` lists the names whose opinions count as evidence.
- `rules` sort each opinion onto the `for` or `against` side of the hypothesis (by `status` and, optionally, a `related` taxon prefix). An opinion that matches no rule is neutral.
- `key_events` are the moments that change the hypothesis's life, each naming an ingested publication:

| Stance | Effect | The cited paper must hold an opinion |
| --- | --- | --- |
| `proposes` | Born (first event only) | for |
| `supports` | Stays alive; ends a contested spell | for |
| `confirms` | Confirmed | for |
| `challenges` | Contested, but still alive | against |
| `refutes` | Dead (a further refutation reinforces it) | against |
| `revives` | Alive again (only while dead) | for |

The build fails if a key event cites a paper that is not in `data/extracted/`, if that paper has no opinion on the creature's taxa on the required side, or if the events break the life story (for example, a paper supporting a refuted hypothesis without a revival first).

Which papers are turning points is a curated judgement. No automatic rule reproduces the histories: PBDB's evidence-weighted accepted-opinion rule never lets Riggs (1903) sink *Brontosaurus*, and "latest paper wins" flips it every few years. The evidence count, however, is not curated. It is every ingested paper with an opinion on the creature's taxa, published from the proposal year on, split into for, against and neutral by the rules. The SQLite tables are `theoretical_creature`, `creature_taxon` and `hypothesis_event`; the web export is `public/data/theoretical/creatures.json`.
