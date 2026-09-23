import type { HypothesisEvent, Stance, TheoreticalCreature } from './types'

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

/** Where a hypothesis stands at a moment in the literature. */
export type LifeState = 'alive' | 'contested' | 'confirmed' | 'dead'

export const LIFE_LABELS: Record<LifeState, string> = {
  alive: 'Alive',
  contested: 'Contested',
  confirmed: 'Confirmed',
  dead: 'Dead',
}

export const STANCE_INFO: Record<Stance, { label: string; side: 'for' | 'against' | 'neutral' }> = {
  proposes: { label: 'Proposed', side: 'for' },
  supports: { label: 'Supported', side: 'for' },
  confirms: { label: 'Confirmed', side: 'for' },
  revives: { label: 'Revived', side: 'for' },
  revises: { label: 'Revised', side: 'neutral' },
  challenges: { label: 'Challenged', side: 'against' },
  refutes: { label: 'Refuted', side: 'against' },
}

export interface LifeSegment {
  from: number
  to: number
  state: LifeState
}

export interface Life {
  /** Events published up to the "known by" year. */
  events: HypothesisEvent[]
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
    case 'revises':
      return state
  }
}

/** Replays a creature's papers, in order, up to and including `untilYear`. */
export function lifeOf(creature: TheoreticalCreature, untilYear: number, now: number): Life {
  const events = creature.events.filter(event => event.publication.year <= untilYear)
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
    segments: segments.filter(segment => segment.to > segment.from || segment === segments.at(-1)),
    state,
    born: events[0]?.publication.year ?? null,
    died,
    support: events.filter(event => STANCE_INFO[event.stance].side === 'for').length,
    opposition: events.filter(event => STANCE_INFO[event.stance].side === 'against').length,
  }
}

export function citation(event: HypothesisEvent): string {
  const { authors, year } = event.publication
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
    case 'revises':
      return svg('rect', { x: x - 1.5, y: y - r, width: 3, height: r * 2, rx: 1, class: className })
  }
}

export function markerSample(stance: Stance): string {
  const node = marker(stance, 10, 9)
  return `<svg width="20" height="18" viewBox="0 0 20 18" aria-hidden="true">${node.outerHTML}</svg>`
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

    const firstYear = Math.min(...creatures.flatMap(creature => creature.events.map(event => event.publication.year)))
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
      row.setAttribute('aria-label', `${creature.name}: ${life.state ? LIFE_LABELS[life.state] : 'not yet proposed'}, ${life.events.length} papers. Show history.`)
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

      // Papers published in the same year fan out slightly so each stays visible.
      const seen = new Map<number, number>()
      for (const event of life.events) {
        const year = event.publication.year
        const repeat = seen.get(year) ?? 0
        seen.set(year, repeat + 1)
        const mark = marker(event.stance, x(year) + repeat * (MARKER * 2 + 2), y)
        mark.addEventListener('pointerenter', pointer => this.showTooltip(creature, event, pointer.clientX, pointer.clientY))
        mark.addEventListener('pointermove', pointer => this.showTooltip(creature, event, pointer.clientX, pointer.clientY))
        mark.addEventListener('pointerleave', () => (this.tooltip.hidden = true))
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

  private showTooltip(creature: TheoreticalCreature, event: HypothesisEvent, clientX: number, clientY: number) {
    const tooltip = this.tooltip
    tooltip.replaceChildren()
    const line = (text: string, className: string) => {
      const node = document.createElement('div')
      node.className = className
      node.textContent = text
      tooltip.append(node)
    }
    line(`${STANCE_INFO[event.stance].label} · ${citation(event)}`, 'tip-value')
    line(creature.name, 'tip-title')
    line(event.summary, 'tip-meta')
    line(event.publication.journal ? `${event.publication.title} — ${event.publication.journal}` : event.publication.title, 'tip-meta')
    tooltip.hidden = false
    const box = tooltip.getBoundingClientRect()
    const left = Math.min(clientX + 14, window.innerWidth - box.width - 8)
    const top = clientY + 16 + box.height > window.innerHeight ? clientY - box.height - 12 : clientY + 16
    tooltip.style.left = `${Math.max(8, left)}px`
    tooltip.style.top = `${Math.max(8, top)}px`
  }
}
