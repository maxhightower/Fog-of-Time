# Scientific evidence and taxonomic history: model audit

Audit of `main` at `9d29065` (September 2026). The audit traced the data from
ingestion to the UI and ran six hard cases through the actual corpus. It then
led to the corrections described in [DATA_MODEL.md](../DATA_MODEL.md). The
machine-readable companions are [model-report.json](model-report.json)
(what the current build derives) and [migration-report.json](migration-report.json)
(current build compared with `9d29065`).

## 1. Path traced

```text
PBDB API ──import_pbdb_references.py──▶ data/extracted/*.json (evidence: fossil_occurrence)
PBDB API ──import_pbdb_opinions.py────▶ data/extracted/*.json (opinions: pbdb_opinion)
hand extraction ──────────────────────▶ data/extracted/doi-*.json (full_text / abstract)
hand curation ────────────────────────▶ data/theoretical/*.json (creatures, turning points)
        │
        ▼ build_data.py (offline)
SQLite: publication, publication_evidence, taxonomic_opinion (+ derived identified_as),
        theoretical_creature, hypothesis_event
        │
        ▼
public/data/timeline/all.json, public/data/theoretical/creatures.json
        │
        ▼
src/creatures.ts (lifeOf replay) · src/creaturesView.ts · src/main.ts
```

## 2. What was already sound (kept)

- **A paper is not a fossil.** `physical_key` separates evidence objects from the
  papers reporting them.
- **An opinion row already has the shape of a claim**: subject name, relation
  (`status`), target (`related_taxon`), basis, source. PBDB's `published_as`
  keeps the literal name when it differs. No new "claim" table was needed. What
  was missing was the meaning of each row, its strength, and its provenance.
- **Replay was causal.** Automatic turning points were computed in publication
  order from earlier opinions only, and the lifeline filtered events by year.
- **Primary-opinion filter.** Only opinions whose author and year match the
  reference are ingested. PBDB "unpublished" compiler lists are excluded.
- **Build determinism.** The build is offline and reproducible, and it failed
  on duplicate publication ids, on unknown papers cited by curated creatures,
  and on curated events whose paper held no opinion on the required side.

## 3. Findings

### 3.1 What a "creature" is (conflations)

| Finding | Evidence |
| --- | --- |
| A creature is a *hypothesis* tracked under a list of **normalized names**. The names are PBDB's current labels for taxon concepts, not the names papers used. | Opinion `taxon_name` for Gilmore 1946 is "Nanotyrannus lancensis"; the paper wrote "Gorgosaurus lancensis" (kept only in `published_as`). |
| Official creatures come from **modern accepted names**: `corpus_creature_taxa` reads `evidence.taxon`, which for PBDB occurrences is PBDB's `accepted_name`. | 571 of 729 evidence reports carry a PBDB accepted name. |
| Genus and species are separate creatures. A species placed in another genus (a recombination) was treated as a plain "belongs to", with no hint that the paper did not use the tracked genus. | 187 claims now carry the assertion `places_in_other_genus`, for example "Brontosaurus excelsus belongs to Apatosaurus" (1903–1964). |
| Specimens exist only as evidence objects. Claims cannot be about a specimen. | All 4,896 claims are about names. |

**Verdict:** the creature abstraction is adequate as a *tracked hypothesis*
once names and concepts are kept apart in every claim. A full concept table was
not justified by the data. PBDB's `taxon_name` already acts as a concept
label, and the missing piece was the literal name next to it.

### 3.2 Publication identity

| Risk | Finding |
| --- | --- |
| False merge by title | `import_pbdb_references.py` skipped any reference whose normalized title matched an existing one. The corpus has 13 title groups with 29 records that are **different works**: *The Dinosauria* 1990 and 2004 chapters, *Encyclopedia of Dinosaurs* entries ("Ceratosauria", "Sauropoda", "Pachycephalosauria"), and Carnegie Museum annual reports. Title-only matching would drop them. |
| DOI normalization | DOIs were compared with `casefold()` only. 6 PBDB DOIs are damaged: 5 have a space or a look-alike slash (`10.1111 ⁄ j.1502-…`), and 1 is missing its `10` prefix (`.1080/08912963.2020.1793979`). Their `https://doi.org/` links were broken. |
| Lost provenance | 15 PBDB references merged into another record (equal DOI and title) left their reference number only in the acquisition manifest, not on the publication. |
| Near duplicates | 6 same-author, same-year pairs looked alike. On inspection every pair is distinct (numbered parts of a series, different conferences, QJGS vs Geological Magazine). None were wrongly merged. |
| Unmerged duplicates | None found. After DOI normalization, no two records share a DOI. |

### 3.3 Evidence versus opinion

- **Name usage was promoted to support.** Every paper reporting a fossil became
  an `identified_as` opinion with `basis: implied`, and every creature rule
  counted it as **for** the hypothesis. The "Toroceratops" rule counted it
  **against**. 384 for-side and 2 neutral opinions were usage only.
- **Usage drove turning points.** 28 official creatures were "born" by usage,
  and 1 contest was "resolved" by it. Usage also counted towards the three-paper
  consensus that ends a contest.
- **Modern names were placed in the claim target.** A derived opinion stored
  PBDB's current accepted name as `related_taxon`. So "Southernmost record of …
  *Stygimoloch*" (2024) read as *Stygimoloch* `identified_as` *Pachycephalosaurus
  wyomingensis*, a claim the paper never made.
- **Abstracts counted as strong.** Every `abstract` or `full_text` opinion was
  treated as evidence-backed whatever its recorded basis.

### 3.4 State vocabulary

- `confirms` / "Confirmed" was an **adjudication**. Nanotyrannus was
  "Confirmed" in 2025 even though Woodward et al. 2020 (argued, *against*) stands
  in the corpus unanswered by anything but the 2025 paper.
- "Dead" and "Refuted" were global verdicts. Curated sinking events rested on
  claims PBDB records as **stated without evidence**: Riggs 1903 for
  *Brontosaurus*, Carr 1999 and Carr & Williamson 2004 for *Nanotyrannus*. A
  revival rested on a bare family placement (Rivera-Sylva & Longrich 2024).
  Nothing checked the strength of a curated turning point.
- **Disagreement disappeared once a verdict was reached.** After *Brontosaurus*
  "died" in 1903, the corpus holds papers that still treat it as valid, stated
  (1904, 1905, 1908, 1915–1917, 1926–1943). The lifeline showed "Dead" for 112
  years.
- The "Official" filter meant "currently alive or confirmed", which mixed
  up rule-based origin and scientific acceptance.

### 3.5 Temporal leakage

| Leak | Where |
| --- | --- |
| The creature detail panel always replayed to `Infinity`. With "Known by" at 1990 it still showed the 2025 status and every later turning point. | `creaturesView.showDetail` |
| Timeline records were titled and filtered by PBDB's current accepted name. The paper's own identification was only in claim text. | `export_web`, `main.showRecordDetail` |
| A derived usage summary said "the accepted name is now …", but the value was really PBDB's name at snapshot time. | `derived_opinions` |
| Creature labels and tracked names are modern. Nothing showed that Gilmore (1946) wrote "Gorgosaurus lancensis". | export, UI |
| PBDB's `basis` classification is a later compiler's judgement, not the paper's own words. | inherent. Now labelled "recorded by a PBDB compiler". |

The automatic replay itself did not leak: each turning point depended only on
earlier opinions.

### 3.6 Provenance gaps

- Derived opinions did not record which occurrence records they came from.
- Turning points did not record whether a curator or a rule chose them, or
  which rule version.
- The UI state (alive, contested, …) was recomputed in TypeScript from the
  events, with no stored cause.
- Merged PBDB reference numbers were not stored on the publication (§3.2).

## 4. Adversarial case studies (actual corpus)

States are corpus states at the end of each year (see DATA_MODEL.md). All are
pinned in `tests/fixtures/case_studies.json`.

### Nanotyrannus (curated)
Published as *Gorgosaurus lancensis* (1946–1976), *Aublysodon lancensis*
(1967), *Albertosaurus lancensis* (1970–1992), and *Nanotyrannus* /
*N. lancensis* from 1988.
**Before:** proposed 1946, supported 1988, refuted 1999, revived 2003, refuted
2004, revived 2024, **confirmed** 2025.
**After:** in use 1946 · contested from 1996 (Carr 1996 synonymy, stated) ·
Currie 2003 defends, Rauhut 2003 disputes · challenged 2004 · **sunk 2020**
(Woodward et al., argued osteohistology) · contested 2024 (Rivera-Sylva &
Longrich still treat it as valid) · **revived 2025** (Zanno & Napoli, argued).
The detail panel shows Zanno & Napoli 2025 and Woodward et al. 2020 side by
side as competing claims.
**Failure modes found:** adjudicating "confirms"; sinking and revival on stated
or bare claims; the 1946 name was hidden. **Remaining limit:** the dispute is
really about specimens (CMNH 7541, BMRP 2002.4.1, NCSM 40000). The corpus has
name-level claims only (see §6).

### Brontosaurus (curated)
**Before:** proposed 1879, refuted 1903 (dead 112 years), revived 2015.
**After:** in use 1879 · **contested 1903–2015**. Riggs's synonymy is stated
without recorded evidence, and later papers keep treating *B. excelsus* as
valid, while others place it in *Apatosaurus* or *Camarasaurus*. Tschopp et al.
2015 (argued) defends it · **contested from 2016** (a stated synonymy).
"Published as" lists *Apatosaurus excelsus* and *Atlantosaurus excelsus*.
**Failure modes found:** a global "dead" hid a century of disagreement in the
corpus.

### Torosaurus / Triceratops ("Toroceratops", curated, inverted hypothesis)
**After:** proposed 2010 (Scannella & Horner, argued) · challenged 2011 (Farke)
· defended 2011 (Scannella & Horner) · challenged 2012 (Longrich & Field) · contested.
**Failure mode found:** its "against" rule counted every paper that reported a
*Torosaurus* fossil as evidence against the synonymy. Those papers are now
usage only.

### Stygimoloch (curated)
**After:** in use 1983 · sunk 2009 (argued) · the same year contested by a stated
defence · revived 2010 (argued) · sunk 2016 (argued) · **contested from 2021**
(later papers still treat it as valid, stated).
**Failure mode found:** the 2024 derived usage row claimed the paper
identified *Stygimoloch* as *Pachycephalosaurus wyomingensis*. Now the paper's
name stays *Stygimoloch spinifer*, and PBDB's current name is kept apart as
`current_name`.

### American cheetah (*Miracinonyx*, curated)
**After:** in use 1979 (as *Acinonyx (Miracinonyx) studeri*), defended 1980 (as
*Crocuta inexpectata* synonymized with *Acinonyx studeri*) and 1992 · sunk 2026.
The sinking claim is an **abstract-level reading** (`direct_abstract_unverified`),
and the UI says so. **Limit:** earlier ancient-DNA work (e.g. Barnett et al. 2005) is not in the
corpus, so the corpus dates the sinking to 2026. That is a coverage gap, not
something the model can fix.

### Tyrannosaurus rex (control, rule-based)
In use from 1905 (Osborn, argued), with one turning point and no state
changes. The control confirms that name usage (179 papers) no longer adds
turning points to stable taxa.

### Also observed: Gorgosaurus (rule-based)
Challenged 1963 · sunk 1964 (argued synonymy with *Deinodon*) · contested from
1967 · revived 1998 (argued). Russell's 1970 sinking into *Albertosaurus* and
the 1990 argued synonymy fall inside an already-contested stretch. The
automatic rule shows them as against-ticks, not as new turning points.

## 5. Corrections made

See DATA_MODEL.md for the model. Summary:

1. `publication_identity.py`: explicit verdicts (`same`, `probable_same`,
   `related`, `conflict`, `distinct`) and DOI normalization that repairs only
   cosmetic damage. Only `same` merges. The build fails on an unmerged `same`
   pair and records every other non-distinct pair. Both importers use the rules.
2. `claims.py`: every opinion gains `name_as_published`, `assertion`,
   `strength` (usage < implied < stated < argued), `authority`,
   `derivation_rule` and `source_records`. Strength never exceeds the recorded basis.
3. `history.py`: name usage is never for or against. Only stated claims move a
   state, and only argued claims sink or revive. `confirms` is gone.
   `recorded` marks a creature known only from usage. Curated turning points
   weaker than their stance need a `rationale`. States (`in_use`, `contested`,
   `sunk`) are derived with a stored cause.
4. Timeline evidence keeps `taxon_as_published` next to the displayed name and
   its `taxon_name_basis`.
5. The UI replays the detail panel to the Known-by year. It shows literal names
   used, competing claims, and each claim's strength, authority and source
   record ids.

## 6. Unresolved limitations

- **Specimen-level claims.** The Nanotyrannus and Torosaurus debates are about
  specimens and growth stages. Claims can now name a `specimen`, but none do:
  PBDB opinions are name-level, and filling this needs full-text reading.
- **Evidence type** (morphological, ontogenetic, histological, molecular,
  phylogenetic) is not recorded. PBDB's basis says only *whether* evidence was
  given.
- **Compiler judgement.** For 4,306 of 4,896 claims, "argued" versus "stated" is
  a PBDB compiler's reading, not re-verified.
- **Concepts** are PBDB's current labels. A split or lump that PBDB records as
  one taxon cannot be told apart.
- **Coverage.** States describe *this corpus*. A missing paper changes the
  story (the Miracinonyx ancient-DNA work).
- **Curated hypotheses** still depend on a curator choosing turning points.
  Validation checks that each rests on a real claim of enough strength. It
  cannot check that the curator chose the right papers.

## 7. UI validation

Checked in headless Chromium against `vite preview` with no console errors:

- [Nanotyrannus, whole corpus](screenshots/nanotyrannus-all.png): names as published, competing claims (Zanno & Napoli 2025 against Woodward et al. 2020), turning points with provenance.
- [Brontosaurus, known by 1950](screenshots/brontosaurus-1950.png): contested since Riggs 1903. No paper after 1950 appears.
- Nanotyrannus with "Known by" at 2010 shows neither the 2020 nor the 2025 paper. At 1950 it is "Published as: Gorgosaurus lancensis".
