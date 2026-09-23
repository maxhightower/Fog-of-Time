export interface DatasetManifest {
  schema_version: string
  dataset_version: string
  physical_evidence_count: number
  publication_report_count: number
  publication_count: number
  theoretical_creature_count?: number
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
  taxon: string
  taxon_rank?: string | null
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

export type Stance = 'proposes' | 'supports' | 'revises' | 'challenges' | 'refutes' | 'revives' | 'confirms'

export interface HypothesisEvent {
  id: string
  stance: Stance
  summary: string
  publication: PublicationSummary
}

/** A hypothesised animal; its life is the life of the hypothesis in the literature. */
export interface TheoreticalCreature {
  id: string
  name: string
  scientific_name?: string | null
  hypothesis: string
  evidence_count: number
  events: HypothesisEvent[]
}
