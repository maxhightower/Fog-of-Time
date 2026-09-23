import type { PublicationSummary, TimelineEvidence } from './types'

export type Precision = TimelineEvidence['age']['precision']
export type ColorBy = 'evidence' | 'dating' | 'none'

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

/** One distinct age window reported by a paper, possibly shared by many records. */
export interface AgeWindow {
  min: number
  max: number
  best: number | null
  precision: Precision
  records: TimelineEvidence[]
}

export interface PaperGroup {
  id: string
  publication: PublicationSummary
  short: string
  records: TimelineEvidence[]
  windows: AgeWindow[]
  min: number
  max: number
}

export function recordWindow(record: TimelineEvidence): AgeWindow {
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

export function groupByPaper(records: TimelineEvidence[]): PaperGroup[] {
  const groups = new Map<string, PaperGroup>()
  for (const record of records) {
    const publication = record.representative_report.publication
    let group = groups.get(publication.id)
    if (!group) {
      group = { id: publication.id, publication, short: shortCitation(publication), records: [], windows: [], min: Infinity, max: -Infinity }
      groups.set(publication.id, group)
    }
    group.records.push(record)
    group.min = Math.min(group.min, record.age.min_ma)
    group.max = Math.max(group.max, record.age.max_ma)
    const window = group.windows.find(
      w => w.min === record.age.min_ma && w.max === record.age.max_ma && w.precision === record.age.precision && w.best === (record.age.best_ma ?? null),
    )
    if (window) window.records.push(record)
    else group.windows.push(recordWindow(record))
  }
  return [...groups.values()].sort((a, b) => b.max - a.max)
}

/**
 * Evidence clarity per screen column, in [0, 1].
 *
 * Each record spreads one unit of "evidence" evenly across its age interval, so a
 * tightly dated record clears a narrow window strongly while a 40-Myr stage range
 * barely thins the fog along its whole length. Points are given the width of
 * `minWidthMyr` (a couple of screen pixels) purely so they remain visible.
 */
export function fogClarity(
  records: TimelineEvidence[],
  from: number,
  to: number,
  columns: number,
  minWidthMyr: number,
  strengthMyr = 4,
): Float32Array {
  const density = new Float32Array(columns)
  const span = from - to
  const columnMyr = span / columns
  for (const record of records) {
    let lo = record.age.min_ma
    let hi = record.age.max_ma
    if (hi - lo < minWidthMyr) {
      const centre = record.age.best_ma ?? (lo + hi) / 2
      lo = centre - minWidthMyr / 2
      hi = centre + minWidthMyr / 2
    }
    if (hi < to || lo > from) continue
    const perMyr = 1 / (hi - lo)
    const first = Math.max(0, Math.floor((from - hi) / columnMyr))
    const last = Math.min(columns - 1, Math.floor((from - lo) / columnMyr))
    for (let column = first; column <= last; column++) {
      const colOld = from - column * columnMyr
      const colYoung = colOld - columnMyr
      const overlap = Math.min(colOld, hi) - Math.max(colYoung, lo)
      if (overlap > 0) density[column] += (overlap / columnMyr) * perMyr
    }
  }

  // Soften column edges so the fog drifts rather than stepping.
  const radius = 3
  const blurred = new Float32Array(columns)
  for (let column = 0; column < columns; column++) {
    let sum = 0
    let count = 0
    for (let offset = -radius; offset <= radius; offset++) {
      const index = column + offset
      if (index >= 0 && index < columns) {
        sum += density[index]
        count++
      }
    }
    blurred[column] = 1 - Math.exp(-(sum / count) * strengthMyr)
  }
  return blurred
}

/** Fraction of [to, from] covered by at least one record's age interval. */
export function coverage(records: TimelineEvidence[], from: number, to: number): number {
  const intervals = records
    .map(record => [Math.max(to, record.age.min_ma), Math.min(from, record.age.max_ma)] as const)
    .filter(([lo, hi]) => hi >= lo)
    .sort((a, b) => a[0] - b[0])
  let covered = 0
  let currentLo = -Infinity
  let currentHi = -Infinity
  for (const [lo, hi] of intervals) {
    if (lo > currentHi) {
      if (currentHi > currentLo) covered += currentHi - currentLo
      currentLo = lo
      currentHi = hi
    } else {
      currentHi = Math.max(currentHi, hi)
    }
  }
  if (currentHi > currentLo) covered += currentHi - currentLo
  return covered / (from - to)
}
