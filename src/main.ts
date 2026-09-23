import './style.css'
import type { DatasetManifest, TimelineEvidence } from './types'

const app = document.querySelector<HTMLDivElement>('#app')
if (!app) throw new Error('Missing #app root')

app.innerHTML = `
  <main class="shell">
    <header class="hero">
      <div>
        <p class="eyebrow">DINOSAUR EVIDENCE EXPLORER</p>
        <h1>Fog of Time</h1>
        <p class="lede">Every mark is physical evidence. Every displayed fact keeps a path back to a publication.</p>
      </div>
      <div id="dataset-status" class="dataset-status" aria-live="polite">Loading local dataset…</div>
    </header>

    <section id="fixture-banner" class="fixture-banner" hidden>
      Development fixtures are loaded. These records test the pipeline and are not scientific evidence.
    </section>

    <section class="controls" aria-label="Timeline filters">
      <label>
        Taxon
        <select id="taxon-filter"><option value="">All taxa</option></select>
      </label>
      <label>
        Evidence
        <select id="type-filter"><option value="">All evidence types</option></select>
      </label>
      <button id="reset-filter" type="button">Reset</button>
    </section>

    <section class="timeline-card" aria-labelledby="timeline-heading">
      <div class="section-heading">
        <div>
          <p class="eyebrow">DEEP TIME</p>
          <h2 id="timeline-heading">252–66 million years ago</h2>
        </div>
        <p id="visible-count" class="muted"></p>
      </div>
      <div id="timeline" class="timeline" role="list" aria-label="Dinosaur fossil evidence timeline"></div>
      <div id="axis" class="axis" aria-hidden="true"></div>
    </section>

    <section class="detail-card" aria-labelledby="detail-heading">
      <p class="eyebrow">SELECTED EVIDENCE</p>
      <div id="detail">
        <h2 id="detail-heading">Choose a point on the timeline</h2>
        <p class="muted">The evidence record, dating basis, specimen identity, and publication provenance will appear here.</p>
      </div>
    </section>
  </main>
`

const status = document.querySelector<HTMLDivElement>('#dataset-status')!
const banner = document.querySelector<HTMLElement>('#fixture-banner')!
const timeline = document.querySelector<HTMLDivElement>('#timeline')!
const axis = document.querySelector<HTMLDivElement>('#axis')!
const detail = document.querySelector<HTMLDivElement>('#detail')!
const taxonFilter = document.querySelector<HTMLSelectElement>('#taxon-filter')!
const typeFilter = document.querySelector<HTMLSelectElement>('#type-filter')!
const resetButton = document.querySelector<HTMLButtonElement>('#reset-filter')!
const visibleCount = document.querySelector<HTMLParagraphElement>('#visible-count')!

let manifest: DatasetManifest
let records: TimelineEvidence[] = []
let selectedKey: string | null = null

function formatAge(record: TimelineEvidence): string {
  const { min_ma, max_ma, best_ma, precision } = record.age
  const point = best_ma ?? min_ma
  if (precision === 'approximate_point') return `~${point.toFixed(2)} Ma`
  if (precision === 'reported_point' || min_ma === max_ma) return `${point.toFixed(2)} Ma`
  const range = `${max_ma.toFixed(2)}–${min_ma.toFixed(2)} Ma`
  return best_ma == null ? range : `${range} · best ${best_ma.toFixed(2)} Ma`
}

function midpoint(record: TimelineEvidence): number {
  return record.age.best_ma ?? (record.age.min_ma + record.age.max_ma) / 2
}

function humanize(value: string): string {
  return value.replaceAll('_', ' ').replace(/\b\w/g, letter => letter.toUpperCase())
}

function option(select: HTMLSelectElement, value: string) {
  const node = document.createElement('option')
  node.value = value
  node.textContent = humanize(value)
  select.append(node)
}

function renderAxis() {
  axis.replaceChildren()
  const ticks = [252, 201.4, 145, 100, 66]
  for (const age of ticks) {
    const position = ((manifest.oldest_ma - age) / (manifest.oldest_ma - manifest.youngest_ma)) * 100
    const tick = document.createElement('div')
    tick.className = 'axis-tick'
    tick.style.left = `${Math.max(0, Math.min(100, position))}%`
    tick.textContent = `${age} Ma`
    axis.append(tick)
  }
}

function showDetail(record: TimelineEvidence) {
  selectedKey = record.physical_key
  detail.replaceChildren()

  const heading = document.createElement('h2')
  heading.id = 'detail-heading'
  heading.textContent = record.taxon

  const meta = document.createElement('p')
  meta.className = 'detail-meta'
  meta.textContent = [
    record.specimen_label || record.physical_key,
    humanize(record.evidence_type),
    formatAge(record),
    record.formation || 'Formation not recorded',
  ].join(' · ')

  const grid = document.createElement('dl')
  grid.className = 'fact-grid'
  const facts: Array<[string, string]> = [
    ['Locality', [record.locality.name, record.locality.region, record.locality.country].filter(Boolean).join(', ')],
    ['Dating', humanize(record.age.method)],
    ['Age basis', record.age.basis || 'Not recorded'],
    ['Material', record.material.length ? record.material.join(', ') : 'Not recorded'],
    ['Paper', record.representative_report.publication.title],
    ['Authors', record.representative_report.publication.authors.join(', ')],
    ['Publication year', String(record.representative_report.publication.year)],
    ['Evidence role', humanize(record.representative_report.evidence_role)],
    ['Reports attached', String(record.report_count)],
  ]
  for (const [label, value] of facts) {
    const dt = document.createElement('dt')
    dt.textContent = label
    const dd = document.createElement('dd')
    dd.textContent = value
    grid.append(dt, dd)
  }

  const claimHeading = document.createElement('h3')
  claimHeading.textContent = 'Claims in representative paper'
  const claims = document.createElement('ul')
  claims.className = 'claims'
  for (const claim of record.representative_report.claims) {
    const item = document.createElement('li')
    const locator = [claim.page && `p. ${claim.page}`, claim.figure && `fig. ${claim.figure}`, claim.table && `table ${claim.table}`]
      .filter(Boolean)
      .join(', ')
    item.textContent = locator ? `${claim.summary} (${locator})` : claim.summary
    claims.append(item)
  }

  detail.append(heading, meta, grid, claimHeading, claims)
  renderTimeline()
}

function filteredRecords(): TimelineEvidence[] {
  return records.filter(record => {
    const taxonMatches = !taxonFilter.value || record.taxon === taxonFilter.value
    const typeMatches = !typeFilter.value || record.evidence_type === typeFilter.value
    return taxonMatches && typeMatches
  })
}

function renderTimeline() {
  const visible = filteredRecords()
  timeline.replaceChildren()
  visibleCount.textContent = `${visible.length} of ${records.length} physical evidence records`

  visible
    .slice()
    .sort((a, b) => midpoint(b) - midpoint(a))
    .forEach((record, index) => {
      const position = ((manifest.oldest_ma - midpoint(record)) / (manifest.oldest_ma - manifest.youngest_ma)) * 100
      const point = document.createElement('button')
      point.type = 'button'
      point.className = 'evidence-point'
      if (record.physical_key === selectedKey) point.classList.add('selected')
      point.style.left = `${Math.max(0, Math.min(100, position))}%`
      point.style.top = `${24 + (index % 5) * 35}px`
      point.setAttribute('role', 'listitem')
      point.setAttribute('aria-label', `${record.taxon}, ${formatAge(record)}`)
      point.title = `${record.taxon} · ${formatAge(record)}`
      point.addEventListener('click', () => showDetail(record))
      timeline.append(point)
    })

  if (!visible.length) {
    const empty = document.createElement('p')
    empty.className = 'empty-state'
    empty.textContent = 'No evidence matches these filters.'
    timeline.append(empty)
  }
}

async function load() {
  try {
    const [manifestResponse, timelineResponse] = await Promise.all([
      fetch('/data/manifest.json'),
      fetch('/data/timeline/all.json'),
    ])
    if (!manifestResponse.ok || !timelineResponse.ok) throw new Error('Static evidence artifacts are missing. Run the data build.')
    manifest = await manifestResponse.json() as DatasetManifest
    records = await timelineResponse.json() as TimelineEvidence[]

    status.textContent = `${manifest.physical_evidence_count} physical records · ${manifest.publication_count} publications`
    banner.hidden = !manifest.development_fixture

    for (const taxon of [...new Set(records.map(record => record.taxon))].sort()) option(taxonFilter, taxon)
    for (const type of [...new Set(records.map(record => record.evidence_type))].sort()) option(typeFilter, type)

    taxonFilter.addEventListener('change', renderTimeline)
    typeFilter.addEventListener('change', renderTimeline)
    resetButton.addEventListener('click', () => {
      taxonFilter.value = ''
      typeFilter.value = ''
      renderTimeline()
    })

    renderAxis()
    renderTimeline()
  } catch (error) {
    status.textContent = error instanceof Error ? error.message : 'Unable to load the local dataset.'
    status.classList.add('error')
  }
}

void load()
