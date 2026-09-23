import type { PublicationSummary, TimelineEvidence } from './types'
import type { AgeWindow } from './model'

export function humanize(value: string): string {
  return value.replaceAll('_', ' ').replace(/\b\w/g, letter => letter.toUpperCase())
}

function trim(value: number, digits = 2): string {
  return Number(value.toFixed(digits)).toString()
}

export function formatMa(value: number, digits = 2): string {
  return value === 0 ? 'Today' : `${trim(value, digits)} Ma`
}

export function formatWindow(window: Pick<AgeWindow, 'min' | 'max' | 'best' | 'precision'>): string {
  const { min, max, best, precision } = window
  const point = best ?? min
  if (precision === 'approximate_point') return `~${trim(point)} Ma`
  if (precision === 'reported_point' || min === max) return `${trim(point)} Ma`
  const range = `${trim(max)}–${trim(min)} Ma`
  const displayed = precision === 'approximate_range' ? `~${range}` : range
  return best == null ? displayed : `${displayed} · best ${trim(best)} Ma`
}

export function formatAge(record: TimelineEvidence): string {
  return formatWindow({ min: record.age.min_ma, max: record.age.max_ma, best: record.age.best_ma ?? null, precision: record.age.precision })
}

export function formatSpan(record: Pick<AgeWindow, 'min' | 'max'>): string {
  const width = record.max - record.min
  return width === 0 ? 'no stated error' : `±${trim(width / 2, 1)} Myr`
}

export const PRECISION_LABELS: Record<TimelineEvidence['age']['precision'], string> = {
  explicit_range: 'Explicit range',
  approximate_range: 'Approximate range',
  derived_interval: 'Derived interval (stage → Ma)',
  reported_point: 'Reported point',
  approximate_point: 'Approximate point',
  unknown: 'Unknown precision',
}

export const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']

/** "March 2019", or just "2019" when the month is unknown. */
export function formatPublished(publication: Pick<PublicationSummary, 'year' | 'month'>): string {
  return publication.month ? `${MONTH_NAMES[publication.month - 1]} ${publication.year}` : String(publication.year)
}

/** A position on the publication-time axis as "2019" or, with months, "Mar 2019". */
export function formatYearValue(value: number, withMonth: boolean): string {
  const year = Math.floor(value + 1e-9)
  if (!withMonth) return String(year)
  const month = Math.min(11, Math.floor((value - year) * 12 + 1e-9))
  return `${MONTHS[month]} ${year}`
}
