export interface DatasetManifest {
  schema_version: string
  dataset_version: string
  physical_evidence_count: number
  publication_report_count: number
  publication_count: number
  theoretical_creature_count?: number
  creature_count?: number
  oldest_ma: number
  youngest_ma: number
  development_fixture: boolean
  representative_policy: string
}

export interface Claim {
  type: string
  summary: string
  page?: string | null
  figure?: string | null
  table?: string | null
}

export interface PublicationSummary {
  id: string
  doi?: string | null
  title: string
  year: number
  /** Month of first publication, 1-12, when known. */
  month?: number | null
  journal?: string | null
  url?: string | null
  authors: string[]
}

export interface TimelineReport {
  id: string
  evidence_role: string
  publication: PublicationSummary
  claims: Claim[]
}

export interface TimelineEvidence {
  physical_key: string
  evidence_type: string
  /** Name shown for grouping and filtering (see taxon_name_basis). */
  taxon: string
  taxon_rank?: string | null
  /** The name the paper itself used for the material. */
  taxon_as_published: string
  /** Whether `taxon` is the name as published or PBDB's current accepted name. */
  taxon_name_basis: 'as_published' | 'pbdb_accepted_name'
  specimen_label?: string | null
  material: string[]
  locality: {
    name: string
    country: string
    region?: string | null
  }
  formation?: string | null
  age: {
    min_ma: number
    max_ma: number
    best_ma?: number | null
    precision: 'explicit_range' | 'approximate_range' | 'reported_point' | 'approximate_point' | 'derived_interval' | 'unknown'
    method: string
    basis?: string | null
  }
  report_count: number
  representative_report: TimelineReport
  development_fixture: boolean
}

export type Stance = 'proposes' | 'recorded' | 'supports' | 'challenges' | 'refutes' | 'revives'
/** "usage": the paper only reported fossils under the name; it argues neither way. */
export type Side = 'for' | 'against' | 'neutral' | 'usage'
/** How a claim was made, weakest first. Only stated and argued claims move a state. */
export type Strength = 'usage' | 'implied' | 'stated' | 'argued'
export type Authority = 'pbdb_compiled' | 'direct_full_text' | 'direct_abstract_unverified' | 'build_derived'
/** Corpus state of a hypothesis: what the ingested literature looked like, not a verdict. */
export type CorpusState = 'in_use' | 'contested' | 'sunk'

/** One ingested paper's claim about a name, with its provenance. */
export interface TaxonomicOpinion {
  id: string
  /** Tracked (normalized) name the claim is filed under. */
  taxon: string
  /** The literal name the paper used. */
  name_as_published: string
  status: string
  related_taxon?: string | null
  assertion: string
  strength: Strength
  authority: Authority
  basis?: string | null
  source: 'pbdb_opinion' | 'full_text' | 'abstract' | 'derived_from_occurrence'
  source_records: string[]
  derivation_rule?: string | null
  /** Derived usage only: the name a later database files the material under. */
  current_name?: string | null
  specimen?: string | null
  summary: string
  side: Side
}

/** A moment that changed the hypothesis's life, resting on one opinion. */
export interface KeyEvent {
  stance: Stance
  publication: PublicationSummary
  opinion: TaxonomicOpinion
  rationale?: string | null
}

/** A change of corpus state and the turning point or opposing claim that caused it. */
export interface StateChange {
  year: number
  state: CorpusState
  cause: 'turning_point' | 'opposing_claim'
  opinion_id: string
  publication: PublicationSummary
}

export interface CreaturePaper {
  publication: PublicationSummary
  side: Side
  opinions: TaxonomicOpinion[]
}

/** A hypothesised animal; its life is the life of the hypothesis in the ingested literature. */
export interface TheoreticalCreature {
  id: string
  name: string
  scientific_name?: string | null
  rank?: string | null
  /** True for a hand-curated theoretical creature; false for an official, rule-based one. */
  curated: boolean
  hypothesis: string
  taxa: string[]
  /** A curated file, or the versioned rule that chose the turning points. */
  turning_points: string
  state_rule: string
  evidence_count: number
  key_events: KeyEvent[]
  states: StateChange[]
  papers: CreaturePaper[]
}
