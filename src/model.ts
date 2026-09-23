import type { PublicationSummary, TimelineEvidence } from './types'
import { formatAge, formatMa, humanize } from './format'

export type Precision = TimelineEvidence['age']['precision']
export type ColorBy = 'evidence' | 'dating' | 'none'
export type GroupBy = 'none' | 'paper' | 'taxon' | 'evidence' | 'dating' | 'country'

export const GROUP_OPTIONS: Array<{ value: GroupBy; label: string }> = [
  { value: 'paper', label: 'Paper' },
  { value: 'taxon', label: 'Taxon' },
  { value: 'evidence', label: 'Evidence type' },
  { value: 'dating', label: 'Dating basis' },
  { value: 'country', label: 'Country' },
  { value: 'none', label: 'No grouping' },
]

export interface Category {
  key: string
  label: string
  /** CSS colour value (a custom property reference). */
  color: string
}

// Three categorical slots validate all-pairs for CVD on the dark surface; anything
// beyond them folds into a neutral "other" slot instead of generating a new hue.
const SERIES_1 = 'var(--series-1)'
const SERIES_2 = 'var(--series-2)'
const SERIES_3 = 'var(--series-3)'
const SERIES_OTHER = 'var(--series-other)'

export const CATEGORIES: Record<ColorBy, Category[]> = {
  evidence: [
    { key: 'body', label: 'Body fossils', color: SERIES_1 },
    { key: 'tissue', label: 'Bone histology & pathology', color: SERIES_2 },
    { key: 'trace', label: 'Tracks, traces, eggs & nests', color: SERIES_3 },
    { key: 'other', label: 'Soft tissue & integument', color: SERIES_OTHER },
  ],
  dating: [
    { key: 'numeric', label: 'Numeric (radiometric) constraint', color: SERIES_1 },
    { key: 'stage', label: 'Stage or epoch converted to Ma', color: SERIES_2 },
    { key: 'context', label: 'Formation or published age context', color: SERIES_3 },
  ],
  none: [{ key: 'all', label: 'Physical evidence', color: 'var(--accent)' }],
}

function evidenceCategory(type: string): string {
  if (type === 'body_fossil') return 'body'
  if (type === 'bone_histology' || type === 'pathology') return 'tissue'
  if (['trackway', 'trace_fossil', 'egg', 'nest'].includes(type)) return 'trace'
  return 'other'
}

function datingCategory(method: string): string {
  if (/radiometric|radioisotopic|bentonite|ash|zircon|isotope/.test(method)) return 'numeric'
  if (method.startsWith('broad_')) return 'context'
  if (/ics_conversion|stage/.test(method)) return 'stage'
  return 'context'
}

export function categoryOf(record: TimelineEvidence, colorBy: ColorBy): Category {
  const key =
    colorBy === 'evidence' ? evidenceCategory(record.evidence_type)
    : colorBy === 'dating' ? datingCategory(record.age.method)
    : 'all'
  const categories = CATEGORIES[colorBy]
  return categories.find(category => category.key === key) ?? categories[categories.length - 1]
}

/** One distinct age window within a group, possibly shared by many records. */
export interface AgeWindow {
  min: number
  max: number
  best: number | null
  precision: Precision
  records: TimelineEvidence[]
}

export interface RecordGroup {
  id: string
  label: string
  /** Secondary description, e.g. a paper's full title. */
  detail: string | null
  records: TimelineEvidence[]
  windows: AgeWindow[]
  min: number
  max: number
}

/** What the horizontal axis measures: estimated geologic age (Ma) or publication year. */
export type TimeAxis = 'age' | 'year'

/**
 * A record's extent on the chosen axis. On the publication-year axis a record
 * fills its whole calendar year, [year, year + 1).
 */
export function recordWindow(record: TimelineEvidence, axis: TimeAxis = 'age'): AgeWindow {
  if (axis === 'year') {
    const year = record.representative_report.publication.year
    return { min: year, max: year + 1, best: null, precision: 'explicit_range', records: [record] }
  }
  return {
    min: record.age.min_ma,
    max: record.age.max_ma,
    best: record.age.best_ma ?? null,
    precision: record.age.precision,
    records: [record],
  }
}

export function shortCitation(publication: PublicationSummary): string {
  const first = publication.authors[0]?.trim().split(/\s+/).pop() ?? 'Unknown'
  const etAl = publication.authors.length > 2 ? ' et al.' : publication.authors.length === 2 ? ` & ${publication.authors[1].trim().split(/\s+/).pop()}` : ''
  return `${first}${etAl} ${publication.year}`
}

function groupKey(record: TimelineEvidence, groupBy: Exclude<GroupBy, 'none'>): { key: string; label: string; detail: string | null } {
  switch (groupBy) {
    case 'paper': {
      const publication = record.representative_report.publication
      return { key: publication.id, label: shortCitation(publication), detail: publication.title }
    }
    case 'taxon':
      return { key: record.taxon, label: record.taxon, detail: null }
    case 'evidence':
      return { key: record.evidence_type, label: humanize(record.evidence_type), detail: null }
    case 'dating': {
      const key = datingCategory(record.age.method)
      return { key, label: CATEGORIES.dating.find(category => category.key === key)!.label, detail: null }
    }
    case 'country':
      return { key: record.locality.country, label: record.locality.country, detail: null }
  }
}

export function groupRecords(records: TimelineEvidence[], groupBy: Exclude<GroupBy, 'none'>, axis: TimeAxis = 'age'): RecordGroup[] {
  const groups = new Map<string, RecordGroup>()
  for (const record of records) {
    const { key, label, detail } = groupKey(record, groupBy)
    const id = `${groupBy}:${key}`
    let group = groups.get(id)
    if (!group) {
      group = { id, label, detail, records: [], windows: [], min: Infinity, max: -Infinity }
      groups.set(id, group)
    }
    group.records.push(record)
    const extent = recordWindow(record, axis)
    group.min = Math.min(group.min, extent.min)
    group.max = Math.max(group.max, extent.max)
    const window = group.windows.find(
      w => w.min === extent.min && w.max === extent.max && w.precision === extent.precision && w.best === extent.best,
    )
    if (window) window.records.push(record)
    else group.windows.push(extent)
  }
  return [...groups.values()].sort((a, b) => b.max - a.max)
}

export type RecordLabel = 'none' | 'taxon-specimen' | 'taxon' | 'specimen' | 'evidence' | 'age' | 'dating' | 'country' | 'formation' | 'paper'
export type GroupLabel = 'none' | 'name' | 'name-count' | 'count' | 'age'

export const RECORD_LABEL_OPTIONS: Array<{ value: RecordLabel; label: string }> = [
  { value: 'taxon-specimen', label: 'Taxon + specimen' },
  { value: 'taxon', label: 'Taxon' },
  { value: 'specimen', label: 'Specimen' },
  { value: 'evidence', label: 'Evidence type' },
  { value: 'age', label: 'Age' },
  { value: 'dating', label: 'Dating method' },
  { value: 'country', label: 'Country' },
  { value: 'formation', label: 'Formation' },
  { value: 'paper', label: 'Paper' },
  { value: 'none', label: 'None' },
]

export const GROUP_LABEL_OPTIONS: Array<{ value: GroupLabel; label: string }> = [
  { value: 'none', label: 'None' },
  { value: 'name', label: 'Group name' },
  { value: 'name-count', label: 'Group name + record count' },
  { value: 'count', label: 'Record count' },
  { value: 'age', label: 'Age span' },
]

export function recordLabelText(record: TimelineEvidence, mode: RecordLabel): string {
  switch (mode) {
    case 'none': return ''
    case 'taxon-specimen': return record.specimen_label ? `${record.taxon} · ${record.specimen_label}` : record.taxon
    case 'taxon': return record.taxon
    case 'specimen': return record.specimen_label || record.physical_key
    case 'evidence': return humanize(record.evidence_type)
    case 'age': return formatAge(record)
    case 'dating': return humanize(record.age.method)
    case 'country': return record.locality.country
    case 'formation': return record.formation || 'Formation not recorded'
    case 'paper': return shortCitation(record.representative_report.publication)
  }
}

export function groupLabelText(group: RecordGroup, mode: GroupLabel): string {
  const count = `${group.records.length} ${group.records.length === 1 ? 'record' : 'records'}`
  switch (mode) {
    case 'none': return ''
    case 'name': return group.label
    case 'name-count': return `${group.label} · ${count}`
    case 'count': return count
    case 'age': return group.min === group.max ? formatMa(group.max) : `${formatMa(group.max)} – ${formatMa(group.min)}`
  }
}
