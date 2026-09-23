import type { CreaturePaper, KeyEvent, PublicationSummary, Side, Stance, TheoreticalCreature } from './types'

const SVG_NS = 'http://www.w3.org/2000/svg'

const LABEL_WIDTH = 190
const ROW_HEIGHT = 44
/** Below this width names sit above each lifeline instead of beside it. */
const COMPACT_WIDTH = 560
const COMPACT_ROW_HEIGHT = 58
/** Softens the log scale so the final year or two are not over-stretched. */
const RECENT_YEARS = 6
const TOP_PADDING = 10
const AXIS_HEIGHT = 26
const RIGHT_PADDING = 14
const MARKER = 6
const TICK = 2.5

/** Where a hypothesis stands at a moment in the literature. */
export type LifeState = 'alive' | 'contested' | 'confirmed' | 'dead'

export const LIFE_LABELS: Record<LifeState, string> = {
  alive: 'Alive',
  contested: 'Contested',
  confirmed: 'Confirmed',
  dead: 'Dead',
}

export const STANCE_INFO: Record<Stance, { label: string; side: Side }> = {
  proposes: { label: 'Proposed', side: 'for' },
  supports: { label: 'Supported', side: 'for' },
  confirms: { label: 'Confirmed', side: 'for' },
  revives: { label: 'Revived', side: 'for' },
  challenges: { label: 'Challenged', side: 'against' },
  refutes: { label: 'Refuted', side: 'against' },
}

export const SIDE_LABELS: Record<Side, string> = { for: 'For', against: 'Against', neutral: 'Neutral' }

export interface LifeSegment {
  from: number
  to: number
  state: LifeState
}

export interface Life {
  /** Key events published up to the "known by" year. */
  events: KeyEvent[]
  /** Every ingested paper with an opinion on the creature, up to that year. */
  papers: CreaturePaper[]
  segments: LifeSegment[]
  /** Null until the hypothesis has been proposed. */
  state: LifeState | null
  born: number | null
  /** Year of the refutation that currently holds, if the hypothesis is dead. */
  died: number | null
  support: number
  opposition: number
}

function nextState(state: LifeState | null, stance: Stance): LifeState | null {
  switch (stance) {
    case 'proposes':
    case 'revives':
      return 'alive'
    case 'supports':
      return state === 'contested' ? 'alive' : state
    case 'confirms':
      return 'confirmed'
    case 'challenges':
      return 'contested'
    case 'refutes':
      return 'dead'
  }
}

/** Replays a creature's papers, in order, up to and including `untilYear`. */
export function lifeOf(creature: TheoreticalCreature, untilYear: number, now: number): Life {
  const events = creature.key_events.filter(event => event.publication.year <= untilYear)
  const papers = creature.papers.filter(paper => paper.publication.year <= untilYear)
  const end = Math.min(untilYear, now) + 1
  const segments: LifeSegment[] = []
  let state: LifeState | null = null
  let died: number | null = null
  for (const event of events) {
    const year = event.publication.year
    const next = nextState(state, event.stance)
    if (next === state) continue
    const open = segments.at(-1)
    if (open) open.to = year
    if (next) segments.push({ from: year, to: end, state: next })
    if (next === 'dead') died = year
    else died = null
    state = next
  }
  return {
    events,
    papers,
    segments: segments.filter(segment => segment.to > segment.from || segment === segments.at(-1)),
    state,
    born: events[0]?.publication.year ?? null,
    died,
    support: papers.filter(paper => paper.side === 'for').length,
    opposition: papers.filter(paper => paper.side === 'against').length,
  }
}

export function citation(publication: PublicationSummary): string {
  const { authors, year } = publication
  const lead = authors.length > 2 ? `${surname(authors[0])} et al.` : authors.map(surname).join(' & ')
  return `${lead} ${year}`
}

function surname(name: string): string {
  return name.trim().split(/\s+/).at(-1) ?? name
}

function svg<K extends keyof SVGElementTagNameMap>(tag: K, attributes: Record<string, string | number> = {}): SVGElementTagNameMap[K] {
  const node = document.createElementNS(SVG_NS, tag)
  for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, String(value))
  return node
}

/** Marker glyph for a paper's stance, centred on (x, y). */
function marker(stance: Stance, x: number, y: number): SVGElement {
  const r = MARKER
  const className = `stance-mark stance-${stance}`
  switch (stance) {
    case 'proposes':
      return svg('circle', { cx: x, cy: y, r, class: className })
    case 'revives':
      return svg('circle', { cx: x, cy: y, r: r - 1, class: `${className} ring` })
    case 'supports':
    case 'confirms':
      return svg('path', { d: `M${x} ${y - r - 1}L${x + r} ${y + r - 1}L${x - r} ${y + r - 1}Z`, class: className })
    case 'challenges':
      return svg('path', { d: `M${x} ${y - r}L${x + r} ${y}L${x} ${y + r}L${x - r} ${y}Z`, class: className })
    case 'refutes':
      return svg('path', { d: `M${x - r} ${y - r}L${x + r} ${y + r}M${x + r} ${y - r}L${x - r} ${y + r}`, class: `${className} cross` })
  }
}

export function markerSample(stance: Stance): string {
  const node = marker(stance, 10, 9)
  return `<svg width="20" height="18" viewBox="0 0 20 18" aria-hidden="true">${node.outerHTML}</svg>`
}

/** Small mark for a paper that argued without changing the hypothesis's life: above the line for, below against. */
function tick(side: Side, x: number, y: number): SVGElement {
  const offset = side === 'for' ? -9 : side === 'against' ? 9 : 0
  return svg('circle', { cx: x, cy: y + offset, r: TICK, class: `paper-tick side-${side}` })
}

export function tickSample(side: Side): string {
  return `<svg width="14" height="18" viewBox="0 0 14 18" aria-hidden="true">${tick(side, 7, 9).outerHTML.replace(/cy="[^"]+"/, 'cy="9"')}</svg>`
}

export interface LifelinesModel {
  creatures: TheoreticalCreature[]
  untilYear: number
  now: number
  selected: string | null
}

/** One row per creature: its hypothesis drawn as a life across publication years. */
export class Lifelines {
  private model: LifelinesModel | null = null

  constructor(
    private readonly root: SVGSVGElement,
    private readonly tooltip: HTMLDivElement,
    private readonly onSelect: (creature: TheoreticalCreature) => void,
  ) {
    new ResizeObserver(() => this.model && this.render(this.model)).observe(root.parentElement!)
  }

  render(model: LifelinesModel) {
    this.model = model
    const { creatures, untilYear, now, selected } = model
    const width = Math.max(280, this.root.parentElement!.clientWidth)
    const compact = width < COMPACT_WIDTH
    const rowHeight = compact ? COMPACT_ROW_HEIGHT : ROW_HEIGHT
    const height = TOP_PADDING + creatures.length * rowHeight + AXIS_HEIGHT
    this.root.setAttribute('width', String(width))
    this.root.setAttribute('height', String(height))
    this.root.setAttribute('viewBox', `0 0 ${width} ${height}`)
    this.root.replaceChildren()

    const firstYear = Math.min(...creatures.flatMap(creature => creature.key_events.map(event => event.publication.year)))
    const plotLeft = compact ? 12 : LABEL_WIDTH
    const plotWidth = width - plotLeft - RIGHT_PADDING
    // Time runs on a log of "years ago", so a debate packed into the last decade
    // gets as much room as one spread over the last century.
    const edge = now + 1
    const ago = (year: number) => Math.log(edge + RECENT_YEARS - year) - Math.log(RECENT_YEARS)
    const oldest = ago(firstYear - Math.max(3, (edge - firstYear) * 0.08))
    const x = (year: number) => plotLeft + (1 - ago(year) / oldest) * plotWidth
    const bottom = TOP_PADDING + creatures.length * rowHeight

    // Year grid and axis, dropping ticks that would crowd their neighbour.
    let lastTick = Infinity
    for (const back of [0, 5, 10, 20, 30, 50, 75, 100, 150, 200, 300, 500]) {
      const year = Math.floor(now / 5) * 5 - back
      if (year < firstYear - 10) break
      const px = x(year)
      if (lastTick - px < 44) continue
      lastTick = px
      this.root.append(svg('line', { x1: px, x2: px, y1: TOP_PADDING, y2: bottom, class: 'grid-line' }))
      const label = svg('text', { x: px, y: bottom + 17, 'text-anchor': 'middle', class: 'axis-label' })
      label.textContent = String(year)
      this.root.append(label)
    }
    this.root.append(svg('line', { x1: plotLeft, x2: plotLeft + plotWidth, y1: bottom, y2: bottom, class: 'axis-line' }))

    // The "known by" horizon: everything to its right is still unwritten.
    if (untilYear < now) {
      const horizon = x(untilYear + 1)
      this.root.append(svg('rect', { x: horizon, y: TOP_PADDING, width: Math.max(0, plotLeft + plotWidth - horizon), height: bottom - TOP_PADDING, class: 'future-fog' }))
    }

    creatures.forEach((creature, index) => {
      const life = lifeOf(creature, untilYear, now)
      const top = TOP_PADDING + index * rowHeight
      const y = compact ? top + rowHeight - 16 : top + rowHeight / 2
      const row = svg('g', { class: `life-row${creature.id === selected ? ' selected' : ''}`, tabindex: 0, role: 'button' })
      row.setAttribute('aria-label', `${creature.name}: ${life.state ? LIFE_LABELS[life.state] : 'not yet proposed'}, ${life.papers.length} papers. Show history.`)
      row.append(svg('rect', { x: 0, y: top + 2, width, height: rowHeight - 4, rx: 8, class: 'hit' }))

      const name = svg('text', { x: 10, y: compact ? top + 18 : y - 3, class: 'life-name' })
      name.textContent = creature.name
      const status = compact
        ? svg('text', { x: width - RIGHT_PADDING, y: top + 18, 'text-anchor': 'end', class: `life-status state-${life.state ?? 'unborn'}` })
        : svg('text', { x: 10, y: y + 12, class: `life-status state-${life.state ?? 'unborn'}` })
      status.textContent = life.state ? `${LIFE_LABELS[life.state]}${life.died ? ` since ${life.died}` : ''}` : 'Not yet proposed'
      row.append(name, status)

      for (const segment of life.segments) {
        const x0 = x(segment.from)
        const x1 = Math.max(x0 + 2, x(segment.to))
        if (segment.state === 'dead') {
          row.append(svg('line', { x1: x0, x2: x1, y1: y, y2: y, class: 'life-dead' }))
        } else {
          row.append(svg('rect', { x: x0, y: y - 5, width: x1 - x0, height: 10, rx: 3, class: `life-bar state-${segment.state}` }))
        }
      }

      // Every other ingested paper that argued the point, as a small tick.
      const keyPapers = new Set(life.events.map(event => event.publication.id))
      for (const paper of life.papers) {
        if (keyPapers.has(paper.publication.id)) continue
        const mark = tick(paper.side, x(paper.publication.year), y)
        this.hover(mark, creature, paper.publication, paper.opinions.map(opinion => opinion.summary), `${SIDE_LABELS[paper.side]} · ${citation(paper.publication)}`)
        row.append(mark)
      }

      // Key papers published in the same year fan out slightly so each stays visible.
      const seen = new Map<number, number>()
      for (const event of life.events) {
        const year = event.publication.year
        const repeat = seen.get(year) ?? 0
        seen.set(year, repeat + 1)
        const mark = marker(event.stance, x(year) + repeat * (MARKER * 2 + 2), y)
        this.hover(mark, creature, event.publication, [event.opinion.summary], `${STANCE_INFO[event.stance].label} · ${citation(event.publication)}`)
        row.append(mark)
      }

      row.addEventListener('click', () => this.onSelect(creature))
      row.addEventListener('keydown', key => {
        if (key.key === 'Enter' || key.key === ' ') {
          key.preventDefault()
          this.onSelect(creature)
        }
      })
      this.root.append(row)
    })
  }

  private hover(mark: SVGElement, creature: TheoreticalCreature, publication: PublicationSummary, lines: string[], heading: string) {
    const show = (pointer: PointerEvent) => this.showTooltip(creature, publication, lines, heading, pointer.clientX, pointer.clientY)
    mark.addEventListener('pointerenter', show)
    mark.addEventListener('pointermove', show)
    mark.addEventListener('pointerleave', () => (this.tooltip.hidden = true))
  }

  private showTooltip(creature: TheoreticalCreature, publication: PublicationSummary, lines: string[], heading: string, clientX: number, clientY: number) {
    const tooltip = this.tooltip
    tooltip.replaceChildren()
    const line = (text: string, className: string) => {
      const node = document.createElement('div')
      node.className = className
      node.textContent = text
      tooltip.append(node)
    }
    line(heading, 'tip-value')
    line(creature.name, 'tip-title')
    for (const text of lines) line(text, 'tip-meta')
    line(publication.journal ? `${publication.title} — ${publication.journal}` : publication.title, 'tip-meta')
    tooltip.hidden = false
    const box = tooltip.getBoundingClientRect()
    const left = Math.min(clientX + 14, window.innerWidth - box.width - 8)
    const top = clientY + 16 + box.height > window.innerHeight ? clientY - box.height - 12 : clientY + 16
    tooltip.style.left = `${Math.max(8, left)}px`
    tooltip.style.top = `${Math.max(8, top)}px`
  }
}
