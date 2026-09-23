import type { TimelineEvidence } from './types'
import { categoryOf, fogClarity, recordWindow, type AgeWindow, type ColorBy, type PaperGroup } from './model'
import { formatMa, formatSpan, formatWindow, humanize, PRECISION_LABELS } from './format'
import { TIMESCALE, type GeoRank } from './timescale'

const SVG_NS = 'http://www.w3.org/2000/svg'

const LANE_PITCH = 22
const PLOT_PADDING = 14
const MIN_PLOT_HEIGHT = 260
const GEO_ROW_HEIGHT = 18
const LABEL_GAP = 6
const POINT_GLOW = 9
const MIN_BAR_WIDTH = 3
const FOG_MAX_ALPHA = 0.66

export type Selection = { kind: 'record'; key: string } | { kind: 'paper'; id: string }

export interface TimelineModel {
  from: number
  to: number
  papers: PaperGroup[]
  records: TimelineEvidence[]
  groupByPaper: boolean
  expanded: ReadonlySet<string>
  colorBy: ColorBy
  showDiscoveries: boolean
  showGeology: boolean
  showFog: boolean
  selection: Selection | null
}

export interface TimelineCallbacks {
  onSelectRecord(record: TimelineEvidence): void
  onSelectPaper(paper: PaperGroup): void
  onViewChange(from: number, to: number): void
}

export interface TimelineElements {
  geology: SVGSVGElement
  scroller: HTMLDivElement
  plot: HTMLDivElement
  fog: HTMLCanvasElement
  bars: SVGSVGElement
  axis: SVGSVGElement
  tooltip: HTMLDivElement
}

type RowKind = 'paper' | 'paper-header' | 'record'

interface Row {
  kind: RowKind
  key: string
  label: string
  windows: AgeWindow[]
  record?: TimelineEvidence
  paper?: PaperGroup
  x0: number
  x1: number
  labelX: number | null
  labelAnchor: 'start' | 'end'
  lane: number
}

interface Block {
  rows: Row[]
  paper?: PaperGroup
  expanded: boolean
}

function svg<K extends keyof SVGElementTagNameMap>(tag: K, attributes: Record<string, string | number> = {}): SVGElementTagNameMap[K] {
  const node = document.createElementNS(SVG_NS, tag)
  for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, String(value))
  return node
}

function niceStep(span: number, targetTicks: number): number {
  const raw = span / Math.max(1, targetTicks)
  const power = 10 ** Math.floor(Math.log10(raw))
  const fraction = raw / power
  const nice = fraction < 1.5 ? 1 : fraction < 3.5 ? 2 : fraction < 7.5 ? 5 : 10
  return nice * power
}

function makeNoisePattern(context: CanvasRenderingContext2D): CanvasPattern | null {
  const size = 256
  const tile = document.createElement('canvas')
  tile.width = size
  tile.height = size
  const tileContext = tile.getContext('2d')
  if (!tileContext) return null
  const image = tileContext.createImageData(size, size)

  // Two octaves of tileable value noise give the fog a soft, uneven body.
  const octave = (cells: number) => {
    const grid = Array.from({ length: cells * cells }, () => Math.random())
    const at = (x: number, y: number) => grid[((y + cells) % cells) * cells + ((x + cells) % cells)]
    return (px: number, py: number) => {
      const gx = (px / size) * cells
      const gy = (py / size) * cells
      const x0 = Math.floor(gx)
      const y0 = Math.floor(gy)
      const tx = (gx - x0) ** 2 * (3 - 2 * (gx - x0))
      const ty = (gy - y0) ** 2 * (3 - 2 * (gy - y0))
      const top = at(x0, y0) * (1 - tx) + at(x0 + 1, y0) * tx
      const bottom = at(x0, y0 + 1) * (1 - tx) + at(x0 + 1, y0 + 1) * tx
      return top * (1 - ty) + bottom * ty
    }
  }
  const coarse = octave(6)
  const fine = octave(24)
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const value = coarse(x, y) * 0.7 + fine(x, y) * 0.3
      const offset = (y * size + x) * 4
      image.data[offset] = 196
      image.data[offset + 1] = 200
      image.data[offset + 2] = 184
      image.data[offset + 3] = Math.round(255 * (0.45 + 0.55 * value))
    }
  }
  tileContext.putImageData(image, 0, 0)
  return context.createPattern(tile, 'repeat')
}

export class Timeline {
  private model: TimelineModel | null = null
  private width = 0
  private measureContext = document.createElement('canvas').getContext('2d')
  private fogPattern: CanvasPattern | null = null
  private drag: { pointerId: number; startX: number; from: number; to: number; moved: boolean } | null = null
  private suppressClick = false

  constructor(private readonly elements: TimelineElements, private readonly callbacks: TimelineCallbacks) {
    new ResizeObserver(() => this.model && this.render(this.model)).observe(elements.scroller)
    this.attachViewControls()
  }

  private x(age: number): number {
    const { from, to } = this.model!
    return ((from - age) / (from - to)) * this.width
  }

  private ageAt(px: number): number {
    const { from, to } = this.model!
    return from - (px / this.width) * (from - to)
  }

  private textWidth(text: string, font = '600 12px Inter, ui-sans-serif, system-ui, sans-serif'): number {
    if (!this.measureContext) return text.length * 7
    this.measureContext.font = font
    return this.measureContext.measureText(text).width
  }

  render(model: TimelineModel) {
    this.model = model
    this.width = Math.max(1, this.elements.scroller.clientWidth)
    const focused = document.activeElement instanceof SVGElement ? document.activeElement.dataset.key : undefined
    this.renderGeology()
    const plotHeight = this.renderBars()
    if (focused) {
      // Re-rendering replaces the rows; keep keyboard focus on the same mark.
      const kind = focused.startsWith('paper') ? ['paper:', 'paper-header:'] : ['record:']
      const key = focused.slice(focused.indexOf(':') + 1)
      const match = kind.map(prefix => this.elements.bars.querySelector<SVGGElement>(`[data-key="${CSS.escape(prefix + key)}"]`)).find(Boolean)
      match?.focus({ preventScroll: true })
    }
    this.renderFog(plotHeight)
    this.renderAxis()
  }

  // ---------------------------------------------------------------- geology

  private renderGeology() {
    const { geology } = this.elements
    const model = this.model!
    geology.replaceChildren()
    geology.style.display = model.showGeology ? '' : 'none'
    if (!model.showGeology) return

    const ranks: GeoRank[] = ['period', 'epoch', 'stage']
    geology.setAttribute('width', String(this.width))
    geology.setAttribute('height', String(ranks.length * GEO_ROW_HEIGHT))
    ranks.forEach((rank, rowIndex) => {
      const y = rowIndex * GEO_ROW_HEIGHT
      const opacity = rank === 'period' ? 0.55 : rank === 'epoch' ? 0.38 : 0.26
      for (const unit of TIMESCALE[rank]) {
        if (unit.end >= model.from || unit.start <= model.to) continue
        const x0 = Math.max(0, this.x(unit.start))
        const x1 = Math.min(this.width, this.x(unit.end))
        const width = x1 - x0
        if (width <= 0.5) continue
        const group = svg('g', { class: 'geo-unit' })
        const title = svg('title')
        title.textContent = `${unit.name} · ${formatMa(unit.start)} – ${formatMa(unit.end)}`
        group.append(
          title,
          svg('rect', { x: x0, y: y + 1, width: Math.max(0.5, width - 1), height: GEO_ROW_HEIGHT - 2, fill: unit.color, 'fill-opacity': opacity }),
        )
        const font = '600 11px Inter, ui-sans-serif, system-ui, sans-serif'
        const label = this.textWidth(unit.name, font) + 8 < width ? unit.name : this.textWidth(unit.abbr, font) + 6 < width ? unit.abbr : ''
        if (label) {
          const text = svg('text', { x: x0 + width / 2, y: y + GEO_ROW_HEIGHT / 2 + 4, 'text-anchor': 'middle', class: 'geo-label' })
          text.textContent = label
          group.append(text)
        }
        geology.append(group)
      }
    })
  }

  // ---------------------------------------------------------------- layout

  private rowGeometry(windows: AgeWindow[], label: string, kind: RowKind): Pick<Row, 'x0' | 'x1' | 'labelX' | 'labelAnchor'> | null {
    let barStart = Infinity
    let barEnd = -Infinity
    for (const window of windows) {
      const isPoint = window.max - window.min === 0
      const start = this.x(window.max) - (isPoint ? POINT_GLOW : 0)
      const end = Math.max(this.x(window.min), this.x(window.max) + MIN_BAR_WIDTH) + (isPoint ? POINT_GLOW : 0)
      barStart = Math.min(barStart, start)
      barEnd = Math.max(barEnd, end)
    }
    if (barEnd < 0 || barStart > this.width) return null

    const font = kind === 'record' ? undefined : '700 12px Inter, ui-sans-serif, system-ui, sans-serif'
    const labelWidth = this.textWidth(label, font)
    if (barEnd + LABEL_GAP + labelWidth <= this.width) {
      return { x0: barStart, x1: barEnd + LABEL_GAP + labelWidth, labelX: barEnd + LABEL_GAP, labelAnchor: 'start' }
    }
    if (barStart - LABEL_GAP - labelWidth >= 0) {
      return { x0: barStart - LABEL_GAP - labelWidth, x1: barEnd, labelX: barStart - LABEL_GAP, labelAnchor: 'end' }
    }
    // No room on either side: ride inside the visible part of a wide bar.
    const visibleStart = Math.max(barStart, 0)
    const visibleEnd = Math.min(barEnd, this.width)
    if (visibleEnd - visibleStart >= labelWidth + 16) {
      return { x0: barStart, x1: barEnd, labelX: visibleStart + 8, labelAnchor: 'start' }
    }
    return { x0: barStart, x1: barEnd, labelX: null, labelAnchor: 'start' }
  }

  private makeRow(kind: RowKind, key: string, label: string, windows: AgeWindow[], extra: Partial<Row>): Row | null {
    const geometry = this.rowGeometry(windows, label, kind)
    return geometry ? { kind, key, label, windows, lane: 0, ...geometry, ...extra } : null
  }

  private recordLabel(record: TimelineEvidence): string {
    return record.specimen_label ? `${record.taxon} · ${record.specimen_label}` : record.taxon
  }

  private buildBlocks(): Block[] {
    const model = this.model!
    const blocks: Block[] = []
    const recordRows = (records: TimelineEvidence[]) =>
      records
        .map(record => this.makeRow('record', record.physical_key, this.recordLabel(record), [recordWindow(record)], { record }))
        .filter((row): row is Row => row !== null)

    if (!model.groupByPaper) {
      for (const row of recordRows(model.records)) blocks.push({ rows: [row], expanded: false })
      return blocks
    }

    for (const paper of model.papers) {
      const count = paper.records.length
      const label = `${paper.short} · ${count} ${count === 1 ? 'record' : 'records'}`
      if (model.expanded.has(paper.id)) {
        const header = this.makeRow('paper-header', paper.id, `▾ ${label}`, [{ min: paper.min, max: paper.max, best: null, precision: 'explicit_range', records: paper.records }], { paper })
        if (!header) continue
        // Pack the paper's records into their own sub-lanes so the block stays together.
        const rows = recordRows([...paper.records].sort((a, b) => b.age.max_ma - a.age.max_ma))
        const laneEnds: number[] = []
        for (const row of rows) {
          let lane = laneEnds.findIndex(end => end + 8 <= row.x0)
          if (lane === -1) lane = laneEnds.push(-Infinity) - 1
          laneEnds[lane] = row.x1
          row.lane = lane + 1
        }
        blocks.push({ rows: [header, ...rows], paper, expanded: true })
      } else {
        const row = this.makeRow('paper', paper.id, label, paper.windows, { paper })
        if (row) blocks.push({ rows: [row], paper, expanded: false })
      }
    }
    return blocks
  }

  private packBlocks(blocks: Block[]): number {
    const laneEnds: number[] = []
    const sorted = blocks
      .map(block => ({ block, start: Math.min(...block.rows.map(row => row.x0)) }))
      .sort((a, b) => a.start - b.start)
    for (const { block } of sorted) {
      const depth = Math.max(...block.rows.map(row => row.lane)) + 1
      let offset = 0
      const fits = (base: number) =>
        block.rows.every(row => {
          const end = laneEnds[base + row.lane]
          return end === undefined || end + 10 <= row.x0
        })
      while (!fits(offset)) offset++
      for (const row of block.rows) {
        row.lane += offset
        const end = block.expanded ? Math.max(...block.rows.map(r => r.x1)) : row.x1
        laneEnds[row.lane] = Math.max(laneEnds[row.lane] ?? -Infinity, end)
      }
      for (let lane = offset; lane < offset + depth; lane++) laneEnds[lane] ??= -Infinity
    }
    return laneEnds.length
  }

  // ---------------------------------------------------------------- bars

  private renderBars(): number {
    const model = this.model!
    const { bars, plot } = this.elements
    bars.replaceChildren()

    const blocks = model.showDiscoveries ? this.buildBlocks() : []
    const laneCount = this.packBlocks(blocks)
    const height = Math.max(MIN_PLOT_HEIGHT, laneCount * LANE_PITCH + PLOT_PADDING * 2)
    bars.setAttribute('width', String(this.width))
    bars.setAttribute('height', String(height))
    plot.style.height = `${height}px`

    const defs = svg('defs')
    bars.append(defs)
    this.renderGrid(height)

    const gradients = new Map<string, string>()
    const gradient = (color: string, kind: 'feather' | 'soft' | 'glow'): string => {
      const key = `${color}|${kind}`
      const existing = gradients.get(key)
      if (existing) return existing
      const id = `g${gradients.size}`
      const node = kind === 'glow' ? svg('radialGradient', { id }) : svg('linearGradient', { id, x1: 0, x2: 1, y1: 0, y2: 0 })
      const stops: Array<[number, number]> =
        kind === 'glow' ? [[0, 1], [0.35, 0.75], [1, 0]]
        : kind === 'feather' ? [[0, 0.12], [0.2, 0.85], [0.8, 0.85], [1, 0.12]]
        : [[0, 0.4], [0.1, 1], [0.9, 1], [1, 0.4]]
      for (const [offset, opacity] of stops) {
        node.append(svg('stop', { offset, style: `stop-color: ${color}; stop-opacity: ${opacity}` }))
      }
      defs.append(node)
      gradients.set(key, id)
      return id
    }

    for (const block of blocks) {
      if (block.expanded) {
        const lanes = block.rows.map(row => row.lane)
        const top = PLOT_PADDING + Math.min(...lanes) * LANE_PITCH - 3
        const x0 = Math.min(...block.rows.map(row => row.x0)) - 6
        const x1 = Math.max(...block.rows.map(row => row.x1)) + 6
        bars.append(svg('rect', { class: 'block-panel', x: x0, y: top, width: x1 - x0, height: (Math.max(...lanes) - Math.min(...lanes) + 1) * LANE_PITCH + 2, rx: 6 }))
      }
      for (const row of block.rows) this.renderRow(row, gradient)
    }

    if (model.showDiscoveries && blocks.length === 0) {
      const text = svg('text', { x: this.width / 2, y: height / 2, 'text-anchor': 'middle', class: 'empty-label' })
      text.textContent = model.records.length ? 'No discoveries in this window — only fog.' : 'No evidence matches these settings.'
      bars.append(text)
    }
    return height
  }

  private renderGrid(height: number) {
    const model = this.model!
    const { bars } = this.elements
    const grid = svg('g', { class: 'grid' })
    const step = niceStep(model.from - model.to, this.width / 110)
    for (let age = Math.floor(model.from / step) * step; age >= model.to; age -= step) {
      const x = this.x(age)
      if (x < 0 || x > this.width) continue
      grid.append(svg('line', { x1: x, x2: x, y1: 0, y2: height, class: 'grid-line' }))
    }
    if (model.showGeology) {
      for (const unit of TIMESCALE.period) {
        const x = this.x(unit.start)
        if (x <= 0 || x >= this.width) continue
        grid.append(svg('line', { x1: x, x2: x, y1: 0, y2: height, class: 'period-line' }))
      }
    }
    bars.append(grid)
  }

  private isSelected(row: Row): boolean {
    const selection = this.model!.selection
    if (!selection) return false
    if (selection.kind === 'record') return row.kind === 'record' && row.key === selection.key
    return row.kind !== 'record' && row.key === selection.id
  }

  private renderRow(row: Row, gradient: (color: string, kind: 'feather' | 'soft' | 'glow') => string) {
    const model = this.model!
    const y = PLOT_PADDING + row.lane * LANE_PITCH
    const centre = y + LANE_PITCH / 2
    const group = svg('g', { class: `row row-${row.kind}`, tabindex: 0, role: 'button', 'data-key': `${row.kind}:${row.key}` })
    if (this.isSelected(row)) group.classList.add('selected')
    group.setAttribute('aria-label', this.ariaLabel(row))

    group.append(svg('rect', { class: 'hit', x: row.x0 - 4, y, width: row.x1 - row.x0 + 8, height: LANE_PITCH, rx: 4 }))

    if (row.kind === 'paper-header') {
      const x0 = this.x(row.paper!.max)
      const x1 = Math.max(this.x(row.paper!.min), x0 + MIN_BAR_WIDTH)
      group.append(svg('line', { class: 'header-line', x1: x0, x2: x1, y1: centre, y2: centre }))
      group.append(svg('line', { class: 'header-line', x1: x0, x2: x0, y1: centre - 4, y2: centre + 4 }))
      group.append(svg('line', { class: 'header-line', x1: x1, x2: x1, y1: centre - 4, y2: centre + 4 }))
    } else {
      const records = row.windows.flatMap(window => window.records)
      const barHeight = row.kind === 'paper' ? 12 : 9
      if (row.windows.length > 1) {
        const xs = row.windows.flatMap(window => [this.x(window.max), this.x(window.min)])
        group.append(svg('line', { class: 'window-link', x1: Math.min(...xs), x2: Math.max(...xs), y1: centre, y2: centre }))
      }
      for (const window of row.windows) {
        const color = categoryOf(window.records[0] ?? records[0], model.colorBy).color
        this.renderWindow(group, window, centre, barHeight, color, gradient)
      }
    }

    if (row.labelX !== null) {
      const text = svg('text', { x: row.labelX, y: centre + 4, 'text-anchor': row.labelAnchor, class: row.kind === 'record' ? 'bar-label' : 'bar-label paper-label' })
      text.textContent = row.label
      group.append(text)
    }

    const activate = () => {
      if (this.suppressClick) return
      if (row.kind === 'record') this.callbacks.onSelectRecord(row.record!)
      else this.callbacks.onSelectPaper(row.paper!)
    }
    group.addEventListener('click', activate)
    group.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault()
        activate()
      }
    })
    group.addEventListener('pointerenter', event => this.showTooltip(row, event.clientX, event.clientY))
    group.addEventListener('pointermove', event => this.showTooltip(row, event.clientX, event.clientY))
    group.addEventListener('pointerleave', () => this.hideTooltip())
    group.addEventListener('focus', () => {
      const box = group.getBoundingClientRect()
      this.showTooltip(row, box.left + Math.min(box.width, 40), box.bottom)
    })
    group.addEventListener('blur', () => this.hideTooltip())
    this.elements.bars.append(group)
  }

  private renderWindow(
    group: SVGGElement,
    window: AgeWindow,
    centre: number,
    height: number,
    color: string,
    gradient: (color: string, kind: 'feather' | 'soft' | 'glow') => string,
  ) {
    const x0 = this.x(window.max)
    const x1 = this.x(window.min)
    const top = centre - height / 2
    const isPoint = window.max === window.min

    if (isPoint && window.precision === 'approximate_point') {
      group.append(svg('circle', { cx: x0, cy: centre, r: POINT_GLOW, fill: `url(#${gradient(color, 'glow')})` }))
      group.append(svg('circle', { cx: x0, cy: centre, r: 3, class: 'point-core', style: `fill: ${color}` }))
    } else if (isPoint) {
      group.append(svg('rect', { x: x0 - 1.5, y: top - 3, width: 3, height: height + 6, rx: 1, style: `fill: ${color}` }))
    } else {
      const width = Math.max(MIN_BAR_WIDTH, x1 - x0)
      const attributes = { x: x0, y: top, width, height, rx: Math.min(4, height / 2, width / 2) }
      if (window.precision === 'explicit_range') group.append(svg('rect', { ...attributes, style: `fill: ${color}` }))
      else if (window.precision === 'approximate_range') group.append(svg('rect', { ...attributes, fill: `url(#${gradient(color, 'soft')})` }))
      else if (window.precision === 'derived_interval') group.append(svg('rect', { ...attributes, fill: `url(#${gradient(color, 'feather')})` }))
      else group.append(svg('rect', { ...attributes, class: 'unknown-bar', style: `stroke: ${color}` }))

      if (window.best != null && window.best < window.max && window.best > window.min) {
        const bx = this.x(window.best)
        group.append(svg('line', { class: 'best-tick', x1: bx, x2: bx, y1: top - 2, y2: top + height + 2 }))
      }
    }
  }

  // ---------------------------------------------------------------- fog

  private renderFog(height: number) {
    const model = this.model!
    const canvas = this.elements.fog
    const ratio = window.devicePixelRatio || 1
    canvas.style.width = `${this.width}px`
    canvas.style.height = `${height}px`
    canvas.width = Math.round(this.width * ratio)
    canvas.height = Math.round(height * ratio)
    canvas.style.display = model.showFog ? '' : 'none'
    if (!model.showFog) return
    const context = canvas.getContext('2d')
    if (!context) return
    context.setTransform(ratio, 0, 0, ratio, 0, 0)
    this.fogPattern ??= makeNoisePattern(context)

    const columns = Math.max(1, Math.round(this.width))
    const myrPerPx = (model.from - model.to) / this.width
    const clarity = fogClarity(model.records, model.from, model.to, columns, 2 * myrPerPx)

    // A one-pixel-tall alpha mask, stretched over the plot, carves clear windows
    // out of the textured fog.
    const mask = document.createElement('canvas')
    mask.width = columns
    mask.height = 1
    const maskContext = mask.getContext('2d')
    if (!maskContext) return
    const pixels = maskContext.createImageData(columns, 1)
    for (let column = 0; column < columns; column++) {
      pixels.data[column * 4 + 3] = Math.round(255 * FOG_MAX_ALPHA * (1 - clarity[column]))
    }
    maskContext.putImageData(pixels, 0, 0)

    context.globalCompositeOperation = 'source-over'
    context.clearRect(0, 0, this.width, height)
    context.fillStyle = this.fogPattern ?? 'rgb(196, 200, 184)'
    context.fillRect(0, 0, this.width, height)
    context.globalCompositeOperation = 'destination-in'
    context.imageSmoothingEnabled = true
    context.drawImage(mask, 0, 0, this.width, height)
    context.globalCompositeOperation = 'source-over'
  }

  // ---------------------------------------------------------------- axis

  private renderAxis() {
    const model = this.model!
    const { axis } = this.elements
    axis.replaceChildren()
    axis.setAttribute('width', String(this.width))
    axis.setAttribute('height', '30')
    const span = model.from - model.to
    const step = niceStep(span, this.width / 110)
    const digits = Math.max(0, -Math.floor(Math.log10(step)))
    axis.append(svg('line', { x1: 0, x2: this.width, y1: 0.5, y2: 0.5, class: 'axis-line' }))
    for (let age = Math.floor(model.from / step) * step; age >= model.to - step / 1000; age -= step) {
      const x = this.x(age)
      if (x < -0.5 || x > this.width + 0.5) continue
      axis.append(svg('line', { x1: x, x2: x, y1: 0, y2: 5, class: 'axis-line' }))
      const anchor = x < 30 ? 'start' : x > this.width - 30 ? 'end' : 'middle'
      const text = svg('text', { x, y: 20, 'text-anchor': anchor, class: 'axis-label' })
      text.textContent = formatMa(Math.abs(age) < step / 1000 ? 0 : age, digits)
      axis.append(text)
    }
  }

  // ---------------------------------------------------------------- tooltip

  private ariaLabel(row: Row): string {
    if (row.kind === 'record') {
      const record = row.record!
      return `${this.recordLabel(record)}, ${formatWindow(row.windows[0])}, ${PRECISION_LABELS[record.age.precision]}`
    }
    const paper = row.paper!
    return `${paper.publication.title}, ${paper.short}, ${paper.records.length} records. ${row.kind === 'paper' ? 'Expand' : 'Collapse'} paper.`
  }

  private showTooltip(row: Row, clientX: number, clientY: number) {
    const { tooltip } = this.elements
    tooltip.replaceChildren()
    const line = (text: string, className: string) => {
      const node = document.createElement('div')
      node.className = className
      node.textContent = text
      tooltip.append(node)
    }
    if (row.kind === 'record') {
      const record = row.record!
      const window = row.windows[0]
      line(formatWindow(window), 'tip-value')
      line(this.recordLabel(record), 'tip-title')
      line(`${PRECISION_LABELS[record.age.precision]} · ${formatSpan(window)}`, 'tip-meta')
      line(`${humanize(record.evidence_type)} · ${humanize(record.age.method)}`, 'tip-meta')
    } else {
      const paper = row.paper!
      line(paper.windows.length === 1 ? formatWindow(paper.windows[0]) : `${paper.windows.length} age windows · ${formatMa(paper.max)} – ${formatMa(paper.min)}`, 'tip-value')
      line(paper.short, 'tip-title')
      line(paper.publication.title, 'tip-meta')
      line(`${paper.records.length} physical evidence ${paper.records.length === 1 ? 'record' : 'records'} · click to ${row.kind === 'paper' ? 'expand' : 'collapse'}`, 'tip-meta')
    }
    tooltip.hidden = false
    const { innerWidth, innerHeight } = window
    const box = tooltip.getBoundingClientRect()
    const left = Math.min(clientX + 14, innerWidth - box.width - 8)
    const top = clientY + 16 + box.height > innerHeight ? clientY - box.height - 12 : clientY + 16
    tooltip.style.left = `${Math.max(8, left)}px`
    tooltip.style.top = `${Math.max(8, top)}px`
  }

  private hideTooltip() {
    this.elements.tooltip.hidden = true
  }

  // ---------------------------------------------------------------- pan & zoom

  zoom(factor: number, anchorPx = this.width / 2) {
    const model = this.model
    if (!model) return
    const anchor = this.ageAt(anchorPx)
    this.callbacks.onViewChange(anchor + (model.from - anchor) * factor, anchor - (anchor - model.to) * factor)
  }

  private attachViewControls() {
    const { scroller } = this.elements
    scroller.addEventListener(
      'wheel',
      event => {
        const model = this.model
        if (!model) return
        const box = scroller.getBoundingClientRect()
        if (event.ctrlKey || event.metaKey) {
          event.preventDefault()
          this.zoom(Math.exp(event.deltaY * 0.0025), event.clientX - box.left)
        } else if (Math.abs(event.deltaX) > Math.abs(event.deltaY) || event.shiftKey) {
          event.preventDefault()
          const delta = Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY
          const shift = (delta / this.width) * (model.from - model.to)
          this.callbacks.onViewChange(model.from - shift, model.to - shift)
        }
      },
      { passive: false },
    )

    scroller.addEventListener('pointerdown', event => {
      if (!this.model || event.button !== 0) return
      this.drag = { pointerId: event.pointerId, startX: event.clientX, from: this.model.from, to: this.model.to, moved: false }
    })
    scroller.addEventListener('pointermove', event => {
      const drag = this.drag
      if (!drag || drag.pointerId !== event.pointerId) return
      const dx = event.clientX - drag.startX
      if (!drag.moved && Math.abs(dx) < 4) return
      if (!drag.moved) {
        drag.moved = true
        scroller.setPointerCapture(event.pointerId)
        scroller.classList.add('panning')
        this.hideTooltip()
      }
      const shift = (dx / this.width) * (drag.from - drag.to)
      this.callbacks.onViewChange(drag.from + shift, drag.to + shift)
    })
    const end = (event: PointerEvent) => {
      const drag = this.drag
      if (!drag || drag.pointerId !== event.pointerId) return
      this.drag = null
      scroller.classList.remove('panning')
      if (drag.moved) {
        this.suppressClick = true
        setTimeout(() => (this.suppressClick = false), 0)
      }
    }
    scroller.addEventListener('pointerup', end)
    scroller.addEventListener('pointercancel', end)
  }
}
