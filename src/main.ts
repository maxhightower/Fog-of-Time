import './style.css'
import type { DatasetManifest, TimelineEvidence } from './types'
import { categoriesFor, categoryOf, GROUP_LABEL_OPTIONS, setTaxonHighlights, TAXON_SLOTS, GROUP_OPTIONS, groupRecords, publicationTime, RECORD_LABEL_OPTIONS, type ColorBy, type GroupBy, type GroupLabel, type RecordLabel, type TimeAxis } from './model'
import { formatAge, formatMa, formatPublished, formatYearValue, humanize, PRECISION_LABELS } from './format'
import { PRESETS, TIMESCALE_OLDEST } from './timescale'
import { Timeline, type Selection } from './timeline'
import { matchesName, nameSuggestions, searchWords } from './names'
import { CreaturesView } from './creaturesView'
import { factGrid } from './dom'

const DEFAULT_VIEW = { from: 500, to: 0 }
const MAX_AGE = TIMESCALE_OLDEST
const MIN_SPAN = 0.5
const MIN_YEAR = 1800
const MAX_YEAR = new Date().getFullYear() + 1
const MIN_YEAR_SPAN = 2 / 12
const MIN_APP_WIDTH = 960
const MAX_APP_WIDTH = 2560
const APP_WIDTH_STEP = 160
const DEFAULT_APP_WIDTH = 1440

const app = document.querySelector<HTMLDivElement>('#app')
if (!app) throw new Error('Missing #app root')

app.innerHTML = `
  <div class="shell">
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

    <nav class="notebook-tabs" role="tablist" aria-label="Notebook sections">
      <button type="button" role="tab" id="tab-deep-time" class="notebook-tab" data-section="deep-time" aria-controls="timeline-page" aria-selected="true">Deep time</button>
      <button type="button" role="tab" id="tab-publication-date" class="notebook-tab" data-section="publication-date" aria-controls="timeline-page" aria-selected="false" tabindex="-1">Publication date</button>
      <button type="button" role="tab" id="tab-creatures" class="notebook-tab" data-section="creatures" aria-controls="creatures-page" aria-selected="false" tabindex="-1">Creatures</button>
    </nav>

    <div class="notebook-page" data-section="deep-time">
    <div id="timeline-page" class="workspace" role="tabpanel" aria-labelledby="tab-deep-time">
      <aside class="layers" aria-label="Timeline layers and filters">
        <section class="panel">
          <h2 class="panel-title">Filters</h2>
          <div class="filter-list">
            <div class="filter-row" data-filter="taxon" hidden>
              <label class="field">Taxon or name
                <input id="taxon-filter" type="search" list="taxon-names" placeholder="e.g. T. rex, Sue, raptor" autocomplete="off" spellcheck="false" />
              </label>
              <datalist id="taxon-names"></datalist>
              <button type="button" class="icon-button remove-filter" aria-label="Remove taxon or name filter">×</button>
            </div>
            <div class="filter-row" data-filter="type" hidden>
              <label class="field">Evidence <select id="type-filter"><option value="">All evidence types</option></select></label>
              <button type="button" class="icon-button remove-filter" aria-label="Remove evidence filter">×</button>
            </div>
            <div class="filter-row" data-filter="country" hidden>
              <label class="field">Country <select id="country-filter"><option value="">All countries</option></select></label>
              <button type="button" class="icon-button remove-filter" aria-label="Remove country filter">×</button>
            </div>
            <div class="filter-row" data-filter="precision" hidden>
              <label class="field">Date precision <select id="precision-filter"><option value="">Any precision</option></select></label>
              <button type="button" class="icon-button remove-filter" aria-label="Remove date precision filter">×</button>
            </div>
          </div>
          <div class="add-filter">
            <button id="add-filter" type="button" class="text-button" aria-haspopup="menu" aria-expanded="false" aria-controls="filter-menu">+ Add filter</button>
            <div id="filter-menu" class="filter-menu" role="menu" hidden></div>
          </div>
          <button id="reset-filter" type="button" class="text-button">Reset filters</button>
        </section>

        <section class="panel">
          <h2 class="panel-title">Layers</h2>

          <div class="layer">
            <div class="layer-options">
              <label class="field">Group by
                <select id="group-by"></select>
              </label>
              <label class="field">Colour by
                <select id="color-by">
                  <option value="evidence">Evidence type</option>
                  <option value="dating">Dating basis</option>
                  <option value="taxon">Taxon or name</option>
                  <option value="none">Single colour</option>
                </select>
              </label>
              <div id="taxon-colours" class="taxon-colours" hidden>
                <p class="layer-note">Up to three taxa or names, each with its own colour. Everything else is “Other names”.</p>
              </div>
            </div>
          </div>

          <div class="layer">
            <label class="toggle"><input id="layer-labels" type="checkbox" checked /> <span>Data labels</span></label>
            <p class="layer-note">Text shown beside each bar.</p>
            <div class="layer-options" id="label-options">
              <label class="field">Group bars
                <select id="label-groups"></select>
              </label>
              <label class="field">Record bars
                <select id="label-records"></select>
              </label>
            </div>
          </div>

          <div class="layer">
            <div class="year-heading">
              <span class="field-label">Known by</span>
              <output id="year-output" for="year-slider">—</output>
            </div>
            <div class="year-control">
              <button id="year-play" type="button" class="icon-button" aria-label="Play discoveries by publication year">▶</button>
              <input id="year-slider" type="range" step="1" aria-label="Show evidence published up to this year" />
            </div>
            <p class="layer-note">Replay how the evidence accumulated as papers were published.</p>
          </div>
        </section>

        <section class="panel">
          <h2 class="panel-title">Display</h2>
          <div class="year-heading">
            <span class="field-label">Maximum width</span>
            <output id="width-output" aria-live="polite"></output>
          </div>
          <div class="width-controls" role="group" aria-label="Maximum width">
            <button id="width-narrower" type="button" class="icon-button" aria-label="Narrower">−</button>
            <button id="width-wider" type="button" class="icon-button" aria-label="Wider">+</button>
            <button id="width-fit" type="button" class="text-button">Fit to screen</button>
          </div>
        </section>
      </aside>

      <main class="main-column">
        <section class="timeline-card" aria-labelledby="timeline-heading">
          <div class="section-heading">
            <div>
              <p id="timeline-eyebrow" class="eyebrow">DEEP TIME</p>
              <h2 id="timeline-heading">500 million years ago – today</h2>
            </div>
            <p id="visible-count" class="muted" aria-live="polite"></p>
          </div>

          <div class="range-controls" role="group" aria-label="Time window">
            <div class="presets" id="presets"></div>
            <div class="range-inputs">
              <label class="field inline">From <input id="range-from" type="number" min="0" max="${MAX_AGE}" step="any" inputmode="decimal" /> <span class="unit">Ma</span></label>
              <label class="field inline">To <input id="range-to" type="number" min="0" max="${MAX_AGE}" step="any" inputmode="decimal" /> <span class="unit">Ma</span></label>
              <div class="zoom-buttons">
                <button id="zoom-out" type="button" class="icon-button" aria-label="Zoom out">−</button>
                <button id="zoom-in" type="button" class="icon-button" aria-label="Zoom in">+</button>
                <button id="zoom-fit" type="button" class="text-button">Fit evidence</button>
                <button id="zoom-reset" type="button" class="text-button">Reset</button>
              </div>
            </div>
          </div>

          <div class="timeline">
            <svg id="geology" class="geology" aria-hidden="true"></svg>
            <div id="scroller" class="scroller">
              <div id="plot" class="plot">
                <svg id="bars" class="bars" role="group" aria-label="Dinosaur evidence timeline"></svg>
              </div>
            </div>
            <svg id="axis" class="axis" aria-hidden="true"></svg>
          </div>
          <p class="hint">Drag to pan · Ctrl/⌘ + scroll or pinch to zoom · click a group to open its records</p>
        </section>

        <section class="detail-card" aria-labelledby="detail-heading">
          <p class="eyebrow">SELECTED EVIDENCE</p>
          <div id="detail">
            <h2 id="detail-heading">Choose a bar on the timeline</h2>
            <p class="muted">The evidence record, dating basis, specimen identity, and publication provenance will appear here.</p>
          </div>
        </section>
      </main>

      <aside id="guides" class="guides" aria-label="Legend">
        <section class="panel">
          <h2 class="panel-title">Legend</h2>
          <div id="color-guide" class="guide">
            <p id="color-guide-title" class="legend-heading">Colour</p>
            <ul id="color-legend" class="legend" aria-label="Colour legend"></ul>
          </div>
          <p id="year-guide" class="layer-note" hidden>On the publication axis each record is a dot at the month its paper was published.</p>
          <div id="shape-guide" class="guide">
            <p class="legend-heading">Bar shape = how the date is known</p>
            <ul id="shape-legend" class="legend shape-legend"></ul>
          </div>
        </section>
      </aside>
    </div>
    <div id="creatures-page" role="tabpanel" aria-labelledby="tab-creatures" hidden></div>
    </div>
  </div>
  <div id="tooltip" class="tooltip" role="tooltip" hidden></div>
`

const $ = <T extends Element>(selector: string) => document.querySelector<T>(selector)!

const status = $<HTMLDivElement>('#dataset-status')
const banner = $<HTMLElement>('#fixture-banner')
const detail = $<HTMLDivElement>('#detail')
const visibleCount = $<HTMLParagraphElement>('#visible-count')
const heading = $<HTMLHeadingElement>('#timeline-heading')
const eyebrow = $<HTMLParagraphElement>('#timeline-eyebrow')
const shapeGuide = $<HTMLDivElement>('#shape-guide')
const yearGuide = $<HTMLParagraphElement>('#year-guide')
const rangeFrom = $<HTMLInputElement>('#range-from')
const rangeTo = $<HTMLInputElement>('#range-to')
const presets = $<HTMLDivElement>('#presets')
const groupBy = $<HTMLSelectElement>('#group-by')
const colorBy = $<HTMLSelectElement>('#color-by')
for (const { value, label } of GROUP_OPTIONS) groupBy.add(new Option(label, value))
const layerLabels = $<HTMLInputElement>('#layer-labels')
const labelOptions = $<HTMLDivElement>('#label-options')
const labelGroups = $<HTMLSelectElement>('#label-groups')
const labelRecords = $<HTMLSelectElement>('#label-records')
for (const { value, label } of GROUP_LABEL_OPTIONS) labelGroups.add(new Option(label, value))
for (const { value, label } of RECORD_LABEL_OPTIONS) labelRecords.add(new Option(label, value))
const colorLegend = $<HTMLUListElement>('#color-legend')
const shapeLegend = $<HTMLUListElement>('#shape-legend')
const colorGuide = $<HTMLDivElement>('#color-guide')
const colorGuideTitle = $<HTMLParagraphElement>('#color-guide-title')
const yearSlider = $<HTMLInputElement>('#year-slider')
const yearOutput = $<HTMLOutputElement>('#year-output')
const yearPlay = $<HTMLButtonElement>('#year-play')
const filters = {
  taxon: $<HTMLInputElement>('#taxon-filter'),
  type: $<HTMLSelectElement>('#type-filter'),
  country: $<HTMLSelectElement>('#country-filter'),
  precision: $<HTMLSelectElement>('#precision-filter'),
}
type FilterKey = keyof typeof filters
const FILTER_LABELS: Record<FilterKey, string> = { taxon: 'Taxon or name', type: 'Evidence type', country: 'Country', precision: 'Date precision' }
const addFilterButton = $<HTMLButtonElement>('#add-filter')
const filterMenu = $<HTMLDivElement>('#filter-menu')
const filterRow = (key: FilterKey) => $<HTMLDivElement>(`.filter-row[data-filter="${key}"]`)

let manifest: DatasetManifest
let records: TimelineEvidence[] = []
const recordNameWords = new Map<TimelineEvidence, string[]>()
let axis: TimeAxis = 'age'
let view = { ...DEFAULT_VIEW }
// Each axis remembers its own window so switching back restores it.
const savedViews: Record<TimeAxis, { from: number; to: number } | null> = { age: null, year: null }
let selection: Selection | null = null
const expanded = new Set<string>()
let playTimer: number | null = null
let frame = 0

function clampView(from: number, to: number) {
  if (axis === 'year') {
    let first = Math.min(from, to)
    let last = Math.max(from, to)
    const span = Math.min(MAX_YEAR - MIN_YEAR, Math.max(MIN_YEAR_SPAN, last - first))
    const centre = (first + last) / 2
    first = Math.max(MIN_YEAR, centre - span / 2)
    last = first + span
    if (last > MAX_YEAR) {
      last = MAX_YEAR
      first = MAX_YEAR - span
    }
    return { from: first, to: last }
  }
  let older = Math.max(from, to)
  let younger = Math.min(from, to)
  const span = Math.min(MAX_AGE, Math.max(MIN_SPAN, older - younger))
  const centre = (older + younger) / 2
  older = centre + span / 2
  younger = centre - span / 2
  if (younger < 0) {
    younger = 0
    older = span
  }
  if (older > MAX_AGE) {
    older = MAX_AGE
    younger = MAX_AGE - span
  }
  return { from: older, to: younger }
}

function roundAge(value: number): number {
  const span = Math.abs(view.from - view.to)
  if (axis === 'year') return Number(value.toFixed(span > 4 ? 0 : 2))
  const digits = span > 100 ? 1 : span > 10 ? 2 : 3
  return Number(value.toFixed(digits))
}

function filteredRecords(): TimelineEvidence[] {
  const year = Number(yearSlider.value)
  // Matches scientific names, specimen labels, common names and nicknames.
  const nameQuery = filters.taxon.value.trim()
  return records.filter(record =>
    (!nameQuery || matchesName(recordNameWords.get(record)!, nameQuery)) &&
    (!filters.type.value || record.evidence_type === filters.type.value) &&
    (!filters.country.value || record.locality.country === filters.country.value) &&
    (!filters.precision.value || record.age.precision === filters.precision.value) &&
    record.representative_report.publication.year <= year,
  )
}

const timeline = new Timeline(
  {
    geology: $<SVGSVGElement>('#geology'),
    scroller: $<HTMLDivElement>('#scroller'),
    plot: $<HTMLDivElement>('#plot'),
    bars: $<SVGSVGElement>('#bars'),
    axis: $<SVGSVGElement>('#axis'),
    tooltip: $<HTMLDivElement>('#tooltip'),
  },
  {
    onSelectRecord: record => {
      selection = { kind: 'record', key: record.physical_key }
      showRecordDetail(record)
      scheduleRender()
    },
    onSelectGroup: group => {
      if (expanded.has(group.id)) expanded.delete(group.id)
      else expanded.add(group.id)
      selection = { kind: 'group', id: group.id }
      scheduleRender()
    },
    onViewChange: (from, to) => setView(from, to),
  },
)

const tooltip = $<HTMLDivElement>('#tooltip')
const creaturesView = new CreaturesView($<HTMLElement>('#creatures-page'), tooltip, () => {})

/** The window Reset returns to: 500 Ma – today, or every publication year in the dataset. */
function defaultView() {
  if (axis === 'age') return { ...DEFAULT_VIEW }
  return publicationSpan(records)
}

/** The publication-time window around a set of records, padded so edge dots stay clear of the frame. */
function publicationSpan(list: TimelineEvidence[]) {
  const times = list.map(record => publicationTime(record.representative_report.publication))
  const first = Math.min(...times)
  const last = Math.max(...times)
  const pad = Math.max(3 / 12, (last - first) * 0.04)
  // Long spans snap to whole years so the From/To boxes and heading read cleanly.
  if (last - first > 4) return { from: Math.floor(first - pad), to: Math.ceil(last + pad) }
  return { from: first - pad, to: last + pad }
}

function switchAxis(next: TimeAxis) {
  if (next === axis) return
  savedViews[axis] = view
  axis = next
  view = clampView((savedViews[axis] ?? defaultView()).from, (savedViews[axis] ?? defaultView()).to)
  // Expanded groups and selection carry over; only the axis-specific controls change.
  const age = axis === 'age'
  presets.hidden = !age
  eyebrow.textContent = age ? 'DEEP TIME' : 'PUBLICATION DATE'
  for (const unit of document.querySelectorAll<HTMLSpanElement>('.range-inputs .unit')) unit.textContent = age ? 'Ma' : ''
  for (const input of [rangeFrom, rangeTo]) {
    input.min = String(age ? 0 : MIN_YEAR)
    input.max = String(age ? MAX_AGE : MAX_YEAR)
    input.step = age ? 'any' : '1'
  }
  shapeGuide.hidden = !age
  yearGuide.hidden = age
  scheduleRender()
}

function setView(from: number, to: number) {
  view = clampView(from, to)
  scheduleRender()
}

function scheduleRender() {
  if (frame) return
  frame = requestAnimationFrame(() => {
    frame = 0
    render()
  })
}

function render() {
  const visible = filteredRecords()
  const grouping = groupBy.value as GroupBy
  const groups = grouping === 'none' ? null : groupRecords(visible, grouping, axis)
  const inView = visible.filter(record => {
    if (axis === 'year') {
      const time = publicationTime(record.representative_report.publication)
      return time >= view.from && time <= view.to
    }
    return record.age.max_ma >= view.to && record.age.min_ma <= view.from
  })

  timeline.render({
    axis,
    from: view.from,
    to: view.to,
    records: visible,
    groups,
    expanded,
    colorBy: colorBy.value as ColorBy,
    selection,
    labels: layerLabels.checked ? { groups: labelGroups.value as GroupLabel, records: labelRecords.value as RecordLabel } : null,
  })

  if (document.activeElement !== rangeFrom) rangeFrom.value = String(roundAge(view.from))
  if (document.activeElement !== rangeTo) rangeTo.value = String(roundAge(view.to))
  heading.textContent =
    axis === 'year'
      ? view.to - view.from > 4
        ? `Published ${roundAge(view.from)} – ${roundAge(view.to)}`
        : `Published ${formatYearValue(view.from, true)} – ${formatYearValue(view.to, true)}`
      : `${formatMa(roundAge(view.from))} – ${view.to === 0 ? 'today' : formatMa(roundAge(view.to))}`
  visibleCount.textContent = `${inView.length} of ${records.length} physical evidence records`
  for (const button of presets.querySelectorAll<HTMLButtonElement>('button')) {
    button.setAttribute('aria-pressed', String(Math.abs(Number(button.dataset.from) - view.from) < 0.01 && Math.abs(Number(button.dataset.to) - view.to) < 0.01))
  }

  renderLegend()
}

// ------------------------------------------------------------------ legends

const SHAPE_SAMPLES: Array<[TimelineEvidence['age']['precision'], string]> = [
  ['explicit_range', '<rect x="2" y="5" width="36" height="8" rx="3" fill="currentColor"/>'],
  ['approximate_range', '<defs><linearGradient id="lg-soft"><stop offset="0" stop-color="currentColor" stop-opacity=".4"/><stop offset=".12" stop-color="currentColor"/><stop offset=".88" stop-color="currentColor"/><stop offset="1" stop-color="currentColor" stop-opacity=".4"/></linearGradient></defs><rect x="2" y="5" width="36" height="8" rx="3" fill="url(#lg-soft)"/>'],
  ['derived_interval', '<defs><linearGradient id="lg-feather"><stop offset="0" stop-color="currentColor" stop-opacity=".12"/><stop offset=".2" stop-color="currentColor" stop-opacity=".85"/><stop offset=".8" stop-color="currentColor" stop-opacity=".85"/><stop offset="1" stop-color="currentColor" stop-opacity=".12"/></linearGradient></defs><rect x="2" y="5" width="36" height="8" rx="3" fill="url(#lg-feather)"/>'],
  ['approximate_point', '<defs><radialGradient id="lg-glow"><stop offset="0" stop-color="currentColor"/><stop offset=".35" stop-color="currentColor" stop-opacity=".75"/><stop offset="1" stop-color="currentColor" stop-opacity="0"/></radialGradient></defs><circle cx="20" cy="9" r="9" fill="url(#lg-glow)"/><circle cx="20" cy="9" r="3" fill="currentColor"/>'],
  ['reported_point', '<rect x="18.5" y="2" width="3" height="14" rx="1" fill="currentColor"/>'],
]

function renderShapeLegend() {
  shapeLegend.replaceChildren()
  for (const [precision, markup] of SHAPE_SAMPLES) {
    const item = document.createElement('li')
    item.innerHTML = `<svg width="40" height="18" viewBox="0 0 40 18" aria-hidden="true">${markup}</svg>`
    const label = document.createElement('span')
    label.textContent = PRECISION_LABELS[precision]
    item.append(label)
    shapeLegend.append(item)
  }
  const best = document.createElement('li')
  best.innerHTML = '<svg width="40" height="18" viewBox="0 0 40 18" aria-hidden="true"><rect x="2" y="5" width="36" height="8" rx="3" fill="currentColor" opacity=".55"/><line x1="24" x2="24" y1="3" y2="15" stroke="var(--text)" stroke-width="2"/></svg>'
  const label = document.createElement('span')
  label.textContent = 'Best estimate inside a range'
  best.append(label)
  shapeLegend.append(best)
}

function renderLegend() {
  labelOptions.hidden = !layerLabels.checked
  const mode = colorBy.value as ColorBy
  taxonColours.hidden = mode !== 'taxon'
  const visible = filteredRecords()
  colorGuide.hidden = mode === 'none'
  colorGuideTitle.textContent = `Colour = ${colorBy.selectedOptions[0]?.textContent?.toLowerCase() ?? ''}`
  colorLegend.replaceChildren()
  if (mode === 'none') return
  for (const category of categoriesFor(mode)) {
    const count = visible.filter(record => categoryOf(record, mode).key === category.key).length
    const item = document.createElement('li')
    const swatch = document.createElement('span')
    swatch.className = 'swatch'
    swatch.style.background = category.color
    const label = document.createElement('span')
    label.textContent = category.label
    const value = document.createElement('span')
    value.className = 'legend-count'
    value.textContent = String(count)
    item.append(swatch, label, value)
    colorLegend.append(item)
  }
}

// ------------------------------------------------------------------ details

function showRecordDetail(record: TimelineEvidence) {
  detail.replaceChildren()
  const title = document.createElement('h2')
  title.id = 'detail-heading'
  title.textContent = record.taxon

  const meta = document.createElement('p')
  meta.className = 'detail-meta'
  meta.textContent = [record.specimen_label || record.physical_key, humanize(record.evidence_type), formatAge(record), record.formation || 'Formation not recorded'].join(' · ')

  const grid = factGrid([
    ['Locality', [record.locality.name, record.locality.region, record.locality.country].filter(Boolean).join(', ')],
    ['Dating', humanize(record.age.method)],
    ['Age basis', record.age.basis || 'Not recorded'],
    ['Material', record.material.length ? record.material.join(', ') : 'Not recorded'],
    ['Paper', record.representative_report.publication.title],
    ['Authors', record.representative_report.publication.authors.join(', ')],
    ['Published', formatPublished(record.representative_report.publication)],
    ['Evidence role', humanize(record.representative_report.evidence_role)],
    ['Reports attached', String(record.report_count)],
  ])

  const claimHeading = document.createElement('h3')
  claimHeading.textContent = 'Claims in representative paper'
  const claims = document.createElement('ul')
  claims.className = 'claims'
  for (const claim of record.representative_report.claims) {
    const item = document.createElement('li')
    const locator = [claim.page && `p. ${claim.page}`, claim.figure && `fig. ${claim.figure}`, claim.table && `table ${claim.table}`].filter(Boolean).join(', ')
    item.textContent = locator ? `${claim.summary} (${locator})` : claim.summary
    claims.append(item)
  }
  detail.append(title, meta, grid, claimHeading, claims)
}

// ------------------------------------------------------------------ controls

function fillOptions(select: HTMLSelectElement, values: string[], label: (value: string) => string = humanize) {
  for (const value of [...new Set(values)].sort()) {
    const node = document.createElement('option')
    node.value = value
    node.textContent = label(value)
    select.append(node)
  }
}

// Filters stay hidden until added from the "Add filter" menu; removing one
// clears its value.
function closeFilterMenu() {
  filterMenu.hidden = true
  addFilterButton.setAttribute('aria-expanded', 'false')
}

function openFilterMenu() {
  filterMenu.replaceChildren()
  for (const key of Object.keys(filters) as FilterKey[]) {
    if (!filterRow(key).hidden) continue
    const item = document.createElement('button')
    item.type = 'button'
    item.role = 'menuitem'
    item.className = 'filter-menu-item'
    item.textContent = FILTER_LABELS[key]
    item.addEventListener('click', () => {
      filterRow(key).hidden = false
      closeFilterMenu()
      updateAddFilter()
      filters[key].focus()
    })
    filterMenu.append(item)
  }
  filterMenu.hidden = false
  addFilterButton.setAttribute('aria-expanded', 'true')
  filterMenu.querySelector<HTMLButtonElement>('button')?.focus()
}

function removeFilter(key: FilterKey) {
  filterRow(key).hidden = true
  filters[key].value = ''
  updateAddFilter()
  scheduleRender()
}

function updateAddFilter() {
  addFilterButton.disabled = (Object.keys(filters) as FilterKey[]).every(key => !filterRow(key).hidden)
}

function wireFilterMenu() {
  addFilterButton.addEventListener('click', () => (filterMenu.hidden ? openFilterMenu() : closeFilterMenu()))
  for (const key of Object.keys(filters) as FilterKey[]) {
    filterRow(key).querySelector<HTMLButtonElement>('.remove-filter')!.addEventListener('click', () => removeFilter(key))
  }
  document.addEventListener('click', event => {
    if (!filterMenu.hidden && !(event.target instanceof Node && (filterMenu.contains(event.target) || addFilterButton.contains(event.target)))) closeFilterMenu()
  })
  filterMenu.addEventListener('keydown', event => {
    const items = [...filterMenu.querySelectorAll<HTMLButtonElement>('button')]
    const index = items.indexOf(document.activeElement as HTMLButtonElement)
    if (event.key === 'Escape') {
      // Only closes the menu; a second Esc clears the page's selections.
      event.preventDefault()
      closeFilterMenu()
      addFilterButton.focus()
    } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      items[(index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length]?.focus()
    }
  })
}

function stopPlaying() {
  if (playTimer !== null) clearInterval(playTimer)
  playTimer = null
  yearPlay.textContent = '▶'
  yearPlay.setAttribute('aria-label', 'Play discoveries by publication year')
}

function updateYear() {
  yearOutput.textContent = Number(yearSlider.value) >= Number(yearSlider.max) ? `${yearSlider.value} (all)` : yearSlider.value
  scheduleRender()
}

function wireControls() {
  for (const preset of PRESETS) {
    const button = document.createElement('button')
    button.type = 'button'
    button.className = 'chip'
    button.textContent = preset.label
    button.dataset.from = String(preset.from)
    button.dataset.to = String(preset.to)
    button.addEventListener('click', () => setView(preset.from, preset.to))
    presets.append(button)
  }

  const applyRange = () => {
    const from = Number(rangeFrom.value)
    const to = Number(rangeTo.value)
    if (Number.isFinite(from) && Number.isFinite(to) && rangeFrom.value !== '' && rangeTo.value !== '') setView(from, to)
  }
  for (const input of [rangeFrom, rangeTo]) {
    input.addEventListener('change', applyRange)
    input.addEventListener('keydown', event => event.key === 'Enter' && applyRange())
  }

  $<HTMLButtonElement>('#zoom-in').addEventListener('click', () => timeline.zoom(0.6))
  $<HTMLButtonElement>('#zoom-out').addEventListener('click', () => timeline.zoom(1 / 0.6))
  $<HTMLButtonElement>('#zoom-reset').addEventListener('click', () => {
    const initial = defaultView()
    setView(initial.from, initial.to)
  })
  wireNotebook()
  wireEscape()

  // Maximum page width: a pixel cap stepped by −/+, or 'fit' for the whole window.
  const widthOutput = $<HTMLOutputElement>('#width-output')
  const narrower = $<HTMLButtonElement>('#width-narrower')
  const wider = $<HTMLButtonElement>('#width-wider')
  const fit = $<HTMLButtonElement>('#width-fit')
  let appWidth: number | 'fit' = DEFAULT_APP_WIDTH
  const applyWidth = () => {
    // 'fit' still keeps the shell's side gutters.
    document.documentElement.style.setProperty('--app-max-width', appWidth === 'fit' ? '100vw' : `${appWidth}px`)
    widthOutput.textContent = appWidth === 'fit' ? 'Full window' : `${appWidth} px`
    narrower.disabled = appWidth !== 'fit' && appWidth <= MIN_APP_WIDTH
    wider.disabled = appWidth === 'fit' || appWidth >= MAX_APP_WIDTH
    fit.setAttribute('aria-pressed', String(appWidth === 'fit'))
  }
  narrower.addEventListener('click', () => {
    // From "fit", step down from the page's current rendered width.
    const current = appWidth === 'fit' ? document.querySelector('.shell')!.getBoundingClientRect().width : appWidth
    appWidth = Math.max(MIN_APP_WIDTH, Math.ceil(current / APP_WIDTH_STEP) * APP_WIDTH_STEP - APP_WIDTH_STEP)
    applyWidth()
  })
  wider.addEventListener('click', () => {
    if (appWidth !== 'fit') appWidth = Math.min(MAX_APP_WIDTH, appWidth + APP_WIDTH_STEP)
    applyWidth()
  })
  fit.addEventListener('click', () => {
    appWidth = 'fit'
    applyWidth()
  })
  applyWidth()

  $<HTMLButtonElement>('#zoom-fit').addEventListener('click', () => {
    const visible = filteredRecords()
    if (!visible.length) return
    if (axis === 'year') {
      const fitted = publicationSpan(visible)
      setView(fitted.from, fitted.to)
      return
    }
    const oldest = Math.max(...visible.map(record => record.age.max_ma))
    const youngest = Math.min(...visible.map(record => record.age.min_ma))
    const pad = Math.max(1, (oldest - youngest) * 0.06)
    setView(oldest + pad, youngest - pad)
  })

  layerLabels.addEventListener('change', scheduleRender)
  colorBy.addEventListener('change', scheduleRender)
  groupBy.addEventListener('change', scheduleRender)
  labelGroups.addEventListener('change', scheduleRender)
  labelRecords.addEventListener('change', scheduleRender)
  for (const select of Object.values(filters)) select.addEventListener('change', scheduleRender)
  filters.taxon.addEventListener('input', scheduleRender)
  wireFilterMenu()
  $<HTMLButtonElement>('#reset-filter').addEventListener('click', () => {
    for (const key of Object.keys(filters) as FilterKey[]) removeFilter(key)
    stopPlaying()
    yearSlider.value = yearSlider.max
    updateYear()
  })

  yearSlider.addEventListener('input', () => {
    stopPlaying()
    updateYear()
  })
  yearPlay.addEventListener('click', () => {
    if (playTimer !== null) {
      stopPlaying()
      return
    }
    if (Number(yearSlider.value) >= Number(yearSlider.max)) yearSlider.value = yearSlider.min
    updateYear()
    yearPlay.textContent = '❚❚'
    yearPlay.setAttribute('aria-label', 'Pause')
    playTimer = window.setInterval(() => {
      const next = Number(yearSlider.value) + 1
      yearSlider.value = String(next)
      updateYear()
      if (next >= Number(yearSlider.max)) stopPlaying()
    }, 650)
  })
}

// ------------------------------------------------------------------ colour by taxon or name

const taxonColours = $<HTMLDivElement>('#taxon-colours')
const taxonInputs: HTMLInputElement[] = []

function applyTaxonColours() {
  setTaxonHighlights(taxonInputs.map(input => {
    const query = input.value.trim()
    return query ? { label: query, matches: (record: TimelineEvidence) => matchesName(recordNameWords.get(record)!, query) } : null
  }))
  scheduleRender()
}

/** Starts on the three species with the most records; each slot is then the viewer's to change. */
function initTaxonColours() {
  const counts = new Map<string, number>()
  for (const record of records) {
    if (record.taxon_rank === 'species') counts.set(record.taxon, (counts.get(record.taxon) ?? 0) + 1)
  }
  const top = [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, TAXON_SLOTS)
  const swatches = ['var(--series-1)', 'var(--series-2)', 'var(--series-3)']
  for (let slot = 0; slot < TAXON_SLOTS; slot++) {
    const label = document.createElement('label')
    label.className = 'field taxon-colour'
    const swatch = document.createElement('span')
    swatch.className = 'swatch'
    swatch.style.background = swatches[slot]
    const input = document.createElement('input')
    input.type = 'search'
    input.setAttribute('list', 'taxon-names')
    input.autocomplete = 'off'
    input.spellcheck = false
    input.placeholder = 'Taxon or name'
    input.setAttribute('aria-label', `Colour ${slot + 1}: taxon or name`)
    input.value = top[slot]?.[0] ?? ''
    input.addEventListener('input', applyTaxonColours)
    label.append(swatch, input)
    taxonColours.append(label)
    taxonInputs.push(input)
  }
  applyTaxonColours()
}

// ------------------------------------------------------------------ notebook sections

type Section = 'deep-time' | 'publication-date' | 'creatures'
const SECTIONS: Section[] = ['deep-time', 'publication-date', 'creatures']
const notebookPage = $<HTMLDivElement>('.notebook-page')
const timelinePage = $<HTMLDivElement>('#timeline-page')
const creaturesPage = $<HTMLDivElement>('#creatures-page')
const tabs = () => [...document.querySelectorAll<HTMLButtonElement>('.notebook-tab')]

function sectionFromHash(): Section {
  const hash = location.hash.slice(1) as Section
  return SECTIONS.includes(hash) ? hash : 'deep-time'
}

/** Like a notebook's section tabs: each tab opens its own page; the timeline tabs share one page and differ by axis. */
function openSection(section: Section, focus = true) {
  for (const tab of tabs()) {
    const active = tab.dataset.section === section
    tab.setAttribute('aria-selected', String(active))
    tab.tabIndex = active ? 0 : -1
    if (active && focus) tab.focus()
  }
  notebookPage.dataset.section = section
  const creaturesOpen = section === 'creatures'
  timelinePage.hidden = creaturesOpen
  creaturesPage.hidden = !creaturesOpen
  timelinePage.setAttribute('aria-labelledby', section === 'publication-date' ? 'tab-publication-date' : 'tab-deep-time')
  if (creaturesOpen) {
    stopPlaying()
    void creaturesView.load()
  } else {
    creaturesView.stop()
    switchAxis(section === 'publication-date' ? 'year' : 'age')
  }
  if (location.hash.slice(1) !== section) history.replaceState(null, '', `#${section}`)
}

function wireNotebook() {
  for (const tab of tabs()) tab.addEventListener('click', () => openSection(tab.dataset.section as Section))
  $<HTMLElement>('.notebook-tabs').addEventListener('keydown', event => {
    const index = tabs().findIndex(tab => tab.getAttribute('aria-selected') === 'true')
    const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0
    if (event.key === 'Home' || event.key === 'End' || step) {
      event.preventDefault()
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? SECTIONS.length - 1 : (index + step + SECTIONS.length) % SECTIONS.length
      openSection(SECTIONS[next])
    }
  })
  window.addEventListener('hashchange', () => openSection(sectionFromHash(), false))
}

// ------------------------------------------------------------------ escape

function showDetailPlaceholder() {
  detail.innerHTML = `
    <h2 id="detail-heading">Choose a bar on the timeline</h2>
    <p class="muted">The evidence record, dating basis, specimen identity, and publication provenance will appear here.</p>`
}

/** Esc clears every selection on the page: timeline bars and groups, creatures, open menus, tooltips and text. */
function clearAllSelections() {
  selection = null
  showDetailPlaceholder()
  creaturesView.clearSelection()
  closeFilterMenu()
  tooltip.hidden = true
  window.getSelection()?.removeAllRanges()
  if (document.activeElement instanceof HTMLElement && document.activeElement !== document.body) document.activeElement.blur()
  scheduleRender()
}

function wireEscape() {
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || event.defaultPrevented) return
    clearAllSelections()
  })
}

async function load() {
  try {
    const [manifestResponse, timelineResponse] = await Promise.all([fetch('/data/manifest.json'), fetch('/data/timeline/all.json')])
    if (!manifestResponse.ok || !timelineResponse.ok) throw new Error('Static evidence artifacts are missing. Run the data build.')
    manifest = (await manifestResponse.json()) as DatasetManifest
    records = (await timelineResponse.json()) as TimelineEvidence[]

    status.textContent = [
      `${manifest.physical_evidence_count} physical records`,
      `${manifest.publication_count} publications`,
      manifest.creature_count ? `${manifest.creature_count} creatures` : null,
    ].filter(Boolean).join(' · ')
    banner.hidden = !manifest.development_fixture

    for (const record of records) recordNameWords.set(record, searchWords(record))
    const nameList = $<HTMLDataListElement>('#taxon-names')
    for (const { value, hint } of nameSuggestions(records)) nameList.append(new Option(hint, value))
    fillOptions(filters.type, records.map(record => record.evidence_type))
    fillOptions(filters.country, records.map(record => record.locality.country), value => value)
    fillOptions(filters.precision, records.map(record => record.age.precision), value => PRECISION_LABELS[value as TimelineEvidence['age']['precision']] ?? humanize(value))

    const years = records.map(record => record.representative_report.publication.year)
    yearSlider.min = String(Math.min(...years))
    yearSlider.max = String(Math.max(...years))
    yearSlider.value = yearSlider.max

    renderShapeLegend()
    wireControls()
    initTaxonColours()
    updateYear()
    openSection(sectionFromHash(), false)
    render()
  } catch (error) {
    status.textContent = error instanceof Error ? error.message : 'Unable to load the local dataset.'
    status.classList.add('error')
  }
}

void load()
