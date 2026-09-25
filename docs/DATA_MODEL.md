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

## Publication dates

`publication.year` is required. `publication.month` (1–12) is optional and records the month of first publication, online or print, whichever came first. Months for the current corpus come from each DOI's Crossref `published` date and were spot-checked against the publisher article pages.

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

## Publication identity

A publication is what every claim is traced to, so two records become one only
on evidence. `scripts/data/publication_identity.py` (`publication-identity/v1`)
compares records and returns a verdict with the rule that produced it:

| Verdict | Rule | Merged? |
| --- | --- | --- |
| `same` | equal normalized DOI **and** equal normalized title | yes: must be merged in `data/extracted`, or the build fails |
| `conflict` | equal DOI, different titles (a book DOI on its chapters), or a DOI shared with an erratum/reply | no, reported |
| `related` | one title is a corrigendum, erratum, reply, comment, supplement or preprint notice | no, reported |
| `probable_same` | no DOI; equal title, year and first-author surname | no, reported for review |
| `distinct` | different DOIs, different titles, or same title in different years or by different authors | no |

Title-only equality is never identity: "Sauropoda" or "Ceratosauria" is a
chapter title in *The Dinosauria* (1990, 2004) and in the *Encyclopedia of
Dinosaurs* (1997). DOIs are normalized by repairing only cosmetic damage
(resolver prefix, whitespace, a look-alike slash, case). A DOI still malformed
afterwards is kept as `doi_raw` with `doi_status: invalid` and never used for
matching. Every known identifier (record id, DOI, PBDB reference numbers,
including those merged into another record by the opinion importer) is stored in
`publication_identifier` with its provenance. Every non-distinct pair is stored in
`publication_identity_issue`.

## Claims: what a paper said about a name

Besides physical evidence, an extraction record may carry `opinions`: the paper's own claims about names. Each says that a taxon belongs to a parent, is a synonym of another, is a nomen dubium, and so on (`taxon`, `published_as`, `status`, `related_taxon`, `basis`, `summary`, `source`, and optionally `specimen` when the claim is about one specimen rather than a name). A paper must contribute evidence, opinions or both.

- **PBDB opinions** (`source: pbdb_opinion`) are snapshotted by `scripts/data/acquisition/import_pbdb_opinions.py`. Only *primary* opinions are kept, meaning the opinion's author and year match the reference it is recorded from.
- **Direct extraction** (`source: full_text` or `abstract`) records a claim read from the paper itself. `abstract` marks a reading that has not been verified against the full text.
- **Name usage** (`status: identified_as`, `source: derived_from_occurrence`) is created by the build: one row per name a paper reports fossils under, using the paper's own name, with the occurrence records it came from. A species also records a use of its genus. PBDB's current name for the material is kept apart as `current_name`, which is context and not the paper's claim.

### Names versus concepts

Each claim has two names:

- `taxon_name`: the **tracked (normalized) name**, PBDB's current label for the taxon concept. Claims are grouped under it.
- `name_as_published`: the **literal name the paper used**, for example *Gorgosaurus lancensis* for Gilmore (1946), which is tracked as *Nanotyrannus lancensis*.

The same split applies to fossils. `publication_evidence.taxon_as_published` keeps the paper's identification, and `taxon_name_basis` says whether the displayed `taxon` is that name or PBDB's accepted name. The UI leads with the historical name and shows the current one only as labelled context. A later classification never rewrites what an earlier paper called something.

### Claim semantics

`scripts/data/claims.py` (`claim-semantics/v1`) derives three fields from each row, deterministically:

| Field | Values |
| --- | --- |
| `assertion` | `uses_name`, `classifies_as_valid`, `places_in_other_genus` (a species kept, but in a genus other than the tracked one), `synonymizes`, `declares_nomen_status`, `nomenclatural_correction`, `invalid_subgroup`, `phylogenetic_placement` |
| `strength` | `usage` < `implied` < `stated` (without evidence) < `argued` (with evidence), taken only from the recorded basis. It is never raised: a direct reading with no recorded basis is `stated`. |
| `authority` | `pbdb_compiled`, `direct_full_text`, `direct_abstract_unverified`, `build_derived` |

Plus `derivation_rule` for build-derived rows and `source_records` (PBDB opinion numbers, occurrence report ids or the extraction file) for every row.

**Name usage is not support.** A paper reporting a fossil under a name used the name. It did not argue that the taxon is valid. Usage is shown as its own side ("name used only") and can never count for or against a hypothesis, move a state, or be a turning point other than `recorded`.

## Creatures

A creature is a **hypothesis** about an animal, tracked under a list of names, whose life is argued over in the ingested claims. Curated creatures live in `data/theoretical/*.json` (schema v3: `data/schema/theoretical-creature.schema.json`). Every genus and species the corpus reports fossils of is also tracked, with the hypothesis that it is a real, distinct taxon (**rule-based**, called "official" in data).

- `taxa` lists the tracked names whose claims count.
- `rules` sort each claim onto the `for` or `against` side (by `status` and, optionally, a `related` taxon prefix). A claim matching no rule is neutral. Rules may not mention `identified_as`.
- `key_events` are the turning points, each naming an ingested publication.

### Turning points

| Stance | Label | Side | Minimum claim strength |
| --- | --- | --- | --- |
| `proposes` | Proposed | for | implied |
| `recorded` | First recorded use | usage | usage (a creature known only from fossils reported under its name) |
| `supports` | Defended | for | stated |
| `challenges` | Challenged | against | stated |
| `refutes` | Sunk | against | argued |
| `revives` | Revived | for | argued |

A curated turning point resting on a weaker claim than its stance needs must give a `rationale`. The build also fails if a turning point cites a paper that is not ingested, or a paper with no claim on the required side, or if the events break the story (for example, defending a sunk hypothesis without a revival first). There is no "confirmed": nothing in the corpus can confirm a hypothesis beyond dispute.

Rule-based creatures follow `automatic_key_events` in `scripts/data/history.py` (`automatic-turning-points/v2`):

- **Proposed** by the first claim treating the name as valid, or **recorded** by the first usage if no such claim exists.
- A **stated** sinking claim (synonym, nomen dubium/nudum/vanum/oblitum) **challenges** an in-use name. An **argued** one **sinks** it.
- A challenge is answered (**defended**) by an argued defence or by three stated ones. Implied claims and usage do not count.
- A sunk name is **revived** only by an argued defence.
- "Replaced by" and similar nomenclatural claims are neutral: the animal lives on under its new name.

### Corpus states

`derive_states` (`corpus-state/v1`) turns turning points and claims into states over publication time. A state describes **the corpus**, not the animal:

- **In use**: the latest turning point treats the name as valid (or records its use), and no stated claim has disputed it since.
- **Contested**: a challenge is open, or a stated claim on the opposite side has appeared since the latest turning point. That covers a sunk name that is still defended, or a defended name that is still sunk.
- **Sunk**: the latest turning point is an argued claim sinking the name, and no stated claim has defended it since.

Each state change is stored in `creature_state` with the turning point or opposing claim that caused it and the rule version. The browser draws these rows and does not compute states itself. Each state uses only claims published at or before it, so "Known by" replays never use later literature. The creature detail panel replays to the same year.

**Paper counts are not consensus.** The UI shows how many papers are for, against, neutral or usage-only, and the latest stated claim on each side ("competing claims"). It never turns a count into a verdict.

### Provenance chain

```text
UI state / lifeline segment
  -> creature_state (cause: turning point or opposing claim, rule version)
  -> hypothesis_event (curated file or automatic rule; rationale if weaker than its floor)
  -> taxonomic_opinion claim (assertion, strength, authority, derivation_rule, source_records)
  -> publication (identifiers with provenance)
  -> source record: PBDB opinion number, PBDB occurrence id, or extraction file
```

The SQLite tables are `theoretical_creature` (with `curated` and `turning_points`), `creature_taxon`, `hypothesis_event` and `creature_state`. The web export `public/data/theoretical/creatures.json` stores each cited publication once and records the rule versions it was built with.

## Migration and validation

The v2 model is derived from the unchanged extraction records at build time, so the migration is reproducible and idempotent. Two builds produce byte-identical outputs. `scripts/data/migration_report.py --baseline <rev>` compares a build with an earlier one. It fails if any publication, opinion or creature disappears, or if any opinion now argues more strongly or on another side. Results for the v1 → v2 migration are in `docs/audit/migration-report.json`, and the audit is in `docs/audit/scientific-model-audit.md`.

`python -m unittest discover -s tests` runs the regression suite. It covers identity rules (`tests/fixtures/publication_identity.json`), claim strength, replay causality, zero orphan references, zero silent publication loss, traceable states, and six adversarial case histories (`tests/fixtures/case_studies.json`: Nanotyrannus, Brontosaurus, Torosaurus/Triceratops, Stygimoloch, the American cheetah, and *Tyrannosaurus rex* as a control).

## Known limitations

- Claims are name-level. The `specimen` field exists, but no claim uses it yet, because PBDB opinions do not identify specimens. Specimen-level disputes (Nanotyrannus, Torosaurus) need full-text reading.
- The kind of evidence behind a claim (morphological, ontogenetic, histological, molecular, phylogenetic) is not recorded.
- For PBDB claims, "argued" versus "stated" is a PBDB compiler's reading of the paper.
- Concepts are PBDB's current labels. Splits and lumps that PBDB records as one taxon cannot be told apart.
- States describe the ingested corpus only. A missing paper changes the story.
