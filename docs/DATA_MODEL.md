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

## Canonical and delivery formats

Checked-in extraction JSON is the reviewable source record. The offline build normalizes those records into `build/fog-of-time.sqlite`. The Vite client does not read SQLite and does not contact scientific APIs; it loads generated artifacts under `public/data/`.

## Representative report policy

The first web exporter uses `latest-publication-report-v0` only as a display policy when multiple papers refer to the same physical key. The database retains all reports. This policy is intentionally explicit and replaceable rather than pretending the newest paper is automatically correct.
