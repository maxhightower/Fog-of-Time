import type { CreaturePaper, KeyEvent, PublicationSummary, Side, Stance, TaxonomicOpinion, TheoreticalCreature } from './types'
import { citation, LIFE_LABELS, lifeOf, Lifelines, markerSample, SIDE_LABELS, STANCE_INFO, tickSample, type Life, type LifeState } from './creatures'
import { factGrid, sourceLine } from './dom'

const THIS_YEAR = new Date().getFullYear()
/** Rows drawn on the lifeline chart before "Show all" is needed. */
const ROW_LIMIT = 40
const PLAY_STEP_MS = 120

type Show = 'all' | 'theoretical' | 'official' | 'contested' | 'dead'
type Sort = 'papers' | 'name' | 'born' | 'eventful'

const SHOW_OPTIONS: Array<{ value: Show; label: string; title: string }> = [
  { value: 'all', label: 'All', title: 'Every tracked creature' },
  { value: 'theoretical', label: 'Theoretical', title: 'Hand-curated hypotheses such as the American cheetah' },
  { value: 'official', label: 'Official', title: 'Currently accepted: alive or confirmed' },
  { value: 'contested', label: 'Contested', title: 'Alive, but challenged without a reply' },
  { value: 'dead', label: 'Dead', title: 'Refuted and not revived' },
]

const SORT_OPTIONS: Array<{ value: Sort; label: string }> = [
  { value: 'papers', label: 'Most papers' },
  { value: 'eventful', label: 'Most turning points' },
  { value: 'born', label: 'First proposed' },
  { value: 'name', label: 'Name' },
]

const LIFE_STATES: LifeState[] = ['alive', 'contested', 'confirmed', 'dead']
const STANCE_ORDER: Stance[] = ['proposes', 'supports', 'confirms', 'revives', 'challenges', 'refutes']
const SIDES: Side[] = ['for', 'against', 'neutral']

interface RawKeyEvent { stance: Stance; publication_id: string; opinion: TaxonomicOpinion }
interface RawPaper { publication_id: string; side: Side; opinions: TaxonomicOpinion[] }
interface RawCreature extends Omit<TheoreticalCreature, 'key_events' | 'papers'> { key_events: RawKeyEvent[]; papers: RawPaper[] }
interface CreatureExport { publications: Record<string, PublicationSummary>; creatures: RawCreature[] }

/** The export stores each publication once; creatures refer to it by id. */
function hydrate(data: CreatureExport): TheoreticalCreature[] {
  const publication = (id: string) => data.publications[id]
  return data.creatures.map(creature => ({
    ...creature,
    key_events: creature.key_events.map((event): KeyEvent => ({ stance: event.stance, opinion: event.opinion, publication: publication(event.publication_id) })),
    papers: creature.papers.map((paper): CreaturePaper => ({ side: paper.side, opinions: paper.opinions, publication: publication(paper.publication_id) })),
  }))
}

function isOfficial(state: LifeState | null): boolean {
  return state === 'alive' || state === 'confirmed'
}

/** The Creatures notebook section: every tracked creature's life in the ingested literature. */
export class CreaturesView {
  private creatures: TheoreticalCreature[] = []
  private loading: Promise<void> | null = null
  private selected: string | null = null
  private show: Show = 'all'
  private showAllRows = false
  private playTimer: number | null = null
  private frame = 0
  private readonly lifelines: Lifelines
  private readonly el: {
    search: HTMLInputElement
    showChips: HTMLDivElement
    sort: HTMLSelectElement
    slider: HTMLInputElement
    yearOutput: HTMLOutputElement
    play: HTMLButtonElement
    list: HTMLUListElement
    listCount: HTMLParagraphElement
    rowNote: HTMLParagraphElement
    rowToggle: HTMLButtonElement
    detail: HTMLDivElement
    status: HTMLParagraphElement
  }

  constructor(private readonly root: HTMLElement, tooltip: HTMLDivElement, private readonly onSelect: () => void) {
    root.innerHTML = `
      <div class="workspace creatures-workspace">
        <aside class="layers" aria-label="Creature list">
          <section class="panel">
            <h2 class="panel-title">Creatures</h2>
            <label class="field">Find
              <input id="creature-search" type="search" placeholder="e.g. Nanotyrannus, cheetah" autocomplete="off" spellcheck="false" />
            </label>
            <div class="field"><span>Show</span>
              <div id="creature-show" class="chip-row" role="group" aria-label="Show creatures"></div>
            </div>
            <label class="field">Sort
              <select id="creature-sort"></select>
            </label>
            <div class="layer">
              <div class="year-heading">
                <span class="field-label">Known by</span>
                <output id="creature-year-output" for="creature-year">—</output>
              </div>
              <div class="year-control">
                <button id="creature-play" type="button" class="icon-button" aria-label="Replay the creatures' lives year by year">▶</button>
                <input id="creature-year" type="range" step="1" aria-label="Show papers published up to this year" />
              </div>
            </div>
            <p id="creature-list-count" class="layer-note" aria-live="polite"></p>
            <ul id="creature-list" class="creature-list"></ul>
            <p class="layer-note">Count = ingested papers with an opinion on the creature (▲ for · ▼ against).</p>
          </section>
        </aside>

        <main class="main-column">
          <section class="creatures-card" aria-labelledby="creatures-heading">
            <div class="section-heading">
              <div>
                <p class="eyebrow">CREATURES</p>
                <h2 id="creatures-heading">Lives of creatures in the literature</h2>
              </div>
              <p class="muted">Every creature is a hypothesis argued over in the ingested papers: born when one proposes it, killed when one refutes it. Official creatures follow a fixed rule; theoretical ones have curated turning points.</p>
            </div>
            <p id="creature-status" class="muted creature-status" aria-live="polite">Loading creatures…</p>
            <div class="lifelines">
              <svg id="lifelines" role="group" aria-label="Creature lifelines"></svg>
            </div>
            <div class="row-limit">
              <p id="creature-row-note" class="hint"></p>
              <button id="creature-row-toggle" type="button" class="text-button" hidden></button>
            </div>
            <div class="life-legend">
              <ul id="life-state-legend" class="legend inline-legend" aria-label="Hypothesis states"></ul>
              <ul id="stance-legend" class="legend inline-legend" aria-label="Paper stances"></ul>
            </div>
            <p class="hint">Recent years are stretched (log of years ago) · hover a mark for the paper · click a row for its full history</p>
          </section>

          <section class="detail-card" aria-labelledby="creature-detail-heading">
            <p class="eyebrow">SELECTED CREATURE</p>
            <div id="creature-detail"></div>
          </section>
        </main>
      </div>`

    const $ = <T extends Element>(selector: string) => root.querySelector<T>(selector)!
    this.el = {
      search: $('#creature-search'),
      showChips: $('#creature-show'),
      sort: $('#creature-sort'),
      slider: $('#creature-year'),
      yearOutput: $('#creature-year-output'),
      play: $('#creature-play'),
      list: $('#creature-list'),
      listCount: $('#creature-list-count'),
      rowNote: $('#creature-row-note'),
      rowToggle: $('#creature-row-toggle'),
      detail: $('#creature-detail'),
      status: $('#creature-status'),
    }
    this.lifelines = new Lifelines($('#lifelines'), tooltip, creature => this.select(creature.id))
    this.placeholder()
    this.renderLegend()
    this.wire()
  }

  /** Fetch the creature export the first time the section opens. */
  load(): Promise<void> {
    this.loading ??= (async () => {
      try {
        const response = await fetch('/data/theoretical/creatures.json')
        if (!response.ok) throw new Error('The creature export is missing. Run the data build.')
        this.creatures = hydrate((await response.json()) as CreatureExport)
        const born = this.creatures.map(creature => creature.key_events[0].publication.year)
        const newest = Math.max(...this.creatures.flatMap(creature => creature.papers.map(paper => paper.publication.year)))
        this.el.slider.min = String(Math.min(...born))
        this.el.slider.max = String(Math.max(newest, ...born))
        this.el.slider.value = this.el.slider.max
        const curated = this.creatures.filter(creature => creature.curated).length
        this.el.status.textContent = `${this.creatures.length} creatures · ${curated} theoretical (curated), ${this.creatures.length - curated} official (rule-based)`
        this.updateYear()
      } catch (error) {
        this.el.status.textContent = error instanceof Error ? error.message : 'Unable to load creatures.'
        this.el.status.classList.add('error')
      }
    })()
    return this.loading
  }

  count(): number {
    return this.creatures.length
  }

  clearSelection() {
    if (this.selected === null) return
    this.selected = null
    this.placeholder()
    this.schedule()
  }

  stop() {
    if (this.playTimer !== null) clearInterval(this.playTimer)
    this.playTimer = null
    this.el.play.textContent = '▶'
    this.el.play.setAttribute('aria-label', "Replay the creatures' lives year by year")
  }

  private select(id: string) {
    this.selected = id
    this.onSelect()
    this.showDetail(this.creatures.find(creature => creature.id === id)!)
    this.schedule()
  }

  private wire() {
    for (const option of SHOW_OPTIONS) {
      const chip = document.createElement('button')
      chip.type = 'button'
      chip.className = 'chip'
      chip.textContent = option.label
      chip.title = option.title
      chip.dataset.show = option.value
      chip.addEventListener('click', () => {
        this.show = option.value
        this.showAllRows = false
        this.schedule()
      })
      this.el.showChips.append(chip)
    }
    for (const { value, label } of SORT_OPTIONS) this.el.sort.add(new Option(label, value))
    this.el.sort.addEventListener('change', () => this.schedule())
    this.el.search.addEventListener('input', () => {
      this.showAllRows = false
      this.schedule()
    })
    this.el.slider.addEventListener('input', () => {
      this.stop()
      this.updateYear()
    })
    this.el.play.addEventListener('click', () => {
      if (this.playTimer !== null) return this.stop()
      if (Number(this.el.slider.value) >= Number(this.el.slider.max)) this.el.slider.value = this.el.slider.min
      this.updateYear()
      this.el.play.textContent = '❚❚'
      this.el.play.setAttribute('aria-label', 'Pause')
      this.playTimer = window.setInterval(() => {
        const next = Number(this.el.slider.value) + 1
        this.el.slider.value = String(next)
        this.updateYear()
        if (next >= Number(this.el.slider.max)) this.stop()
      }, PLAY_STEP_MS)
    })
    this.el.rowToggle.addEventListener('click', () => {
      this.showAllRows = !this.showAllRows
      this.schedule()
    })
  }

  private updateYear() {
    const { slider, yearOutput } = this.el
    yearOutput.textContent = Number(slider.value) >= Number(slider.max) ? `${slider.value} (all)` : slider.value
    this.schedule()
  }

  private schedule() {
    if (this.frame) return
    this.frame = requestAnimationFrame(() => {
      this.frame = 0
      this.render()
    })
  }

  /** Creatures passing the search and "Show" filter, in the chosen order, with their lives as of the slider year. */
  private visible(): Array<{ creature: TheoreticalCreature; life: Life }> {
    const year = Number(this.el.slider.value)
    const query = this.el.search.value.trim().toLowerCase()
    const rows = this.creatures
      .filter(creature => !query || [creature.name, creature.scientific_name ?? '', ...creature.taxa].some(name => name.toLowerCase().includes(query)))
      .map(creature => ({ creature, life: lifeOf(creature, year, THIS_YEAR) }))
      .filter(({ creature, life }) => {
        if (life.state === null) return false
        switch (this.show) {
          case 'theoretical': return creature.curated
          case 'official': return isOfficial(life.state)
          case 'contested': return life.state === 'contested'
          case 'dead': return life.state === 'dead'
          default: return true
        }
      })
    const sort = this.el.sort.value as Sort
    const by: Record<Sort, (a: (typeof rows)[number], b: (typeof rows)[number]) => number> = {
      papers: (a, b) => b.life.papers.length - a.life.papers.length,
      eventful: (a, b) => b.life.events.length - a.life.events.length,
      born: (a, b) => (a.life.born ?? 0) - (b.life.born ?? 0),
      name: () => 0,
    }
    return rows.sort((a, b) => by[sort](a, b) || a.creature.name.localeCompare(b.creature.name))
  }

  private render() {
    for (const chip of this.el.showChips.querySelectorAll<HTMLButtonElement>('button')) {
      chip.setAttribute('aria-pressed', String(chip.dataset.show === this.show))
    }
    if (!this.creatures.length) return
    const rows = this.visible()
    const year = Number(this.el.slider.value)
    const drawn = this.showAllRows ? rows : rows.slice(0, ROW_LIMIT)
    this.lifelines.render({ creatures: drawn.map(row => row.creature), untilYear: year, now: THIS_YEAR, selected: this.selected })

    this.el.rowNote.textContent = rows.length === 0 ? 'No creatures match.' : rows.length > ROW_LIMIT && !this.showAllRows ? `Showing the first ${ROW_LIMIT} of ${rows.length} creatures.` : `${rows.length} creatures.`
    this.el.rowToggle.hidden = rows.length <= ROW_LIMIT
    this.el.rowToggle.textContent = this.showAllRows ? `Show first ${ROW_LIMIT}` : `Show all ${rows.length}`
    this.el.listCount.textContent = `${rows.length} of ${this.creatures.length} creatures`

    this.el.list.replaceChildren()
    for (const { creature, life } of rows) {
      const item = document.createElement('li')
      const button = document.createElement('button')
      button.type = 'button'
      button.className = 'creature-item'
      button.setAttribute('aria-pressed', String(creature.id === this.selected))
      button.setAttribute('aria-label', `${creature.name}, ${life.state ? LIFE_LABELS[life.state] : 'not yet proposed'}, ${life.papers.length} pieces of evidence: ${life.support} for, ${life.opposition} against`)

      const dot = document.createElement('span')
      dot.className = `state-dot state-${life.state ?? 'unborn'}`
      dot.title = life.state ? LIFE_LABELS[life.state] : 'Not yet proposed'
      const names = document.createElement('span')
      names.className = 'creature-names'
      const name = document.createElement('span')
      name.className = 'creature-name'
      name.textContent = creature.name
      const detail = document.createElement('span')
      detail.className = 'creature-scientific'
      detail.textContent = creature.curated ? `${creature.scientific_name ?? ''} · theoretical` : creature.rank ?? ''
      names.append(name, detail)
      const count = document.createElement('span')
      count.className = 'creature-count'
      count.innerHTML = `<strong>${life.papers.length}</strong><span class="creature-split">▲${life.support} ▼${life.opposition}</span>`
      button.append(dot, names, count)
      button.addEventListener('click', () => this.select(creature.id))
      item.append(button)
      this.el.list.append(item)
    }
  }

  private renderLegend() {
    const states = this.root.querySelector<HTMLUListElement>('#life-state-legend')!
    for (const state of LIFE_STATES) {
      const item = document.createElement('li')
      item.innerHTML = `<span class="life-swatch state-${state}"></span>`
      item.append(LIFE_LABELS[state])
      states.append(item)
    }
    const stances = this.root.querySelector<HTMLUListElement>('#stance-legend')!
    for (const stance of STANCE_ORDER) {
      const item = document.createElement('li')
      item.innerHTML = markerSample(stance)
      item.append(STANCE_INFO[stance].label)
      stances.append(item)
    }
    for (const side of SIDES) {
      const item = document.createElement('li')
      item.innerHTML = tickSample(side)
      item.append(`Other paper ${SIDE_LABELS[side].toLowerCase()}`)
      stances.append(item)
    }
  }

  private placeholder() {
    this.el.detail.innerHTML = `
      <h2 id="creature-detail-heading">Choose a creature</h2>
      <p class="muted">Its hypothesis, turning points and every ingested paper behind its evidence count will appear here.</p>`
  }

  private showDetail(creature: TheoreticalCreature) {
    const detail = this.el.detail
    detail.replaceChildren()
    const life = lifeOf(creature, Infinity, THIS_YEAR)
    const title = document.createElement('h2')
    title.id = 'creature-detail-heading'
    title.textContent = creature.name

    const meta = document.createElement('p')
    meta.className = 'detail-meta'
    const kind = creature.curated ? 'Theoretical (curated turning points)' : 'Official (rule-based turning points)'
    meta.textContent = [creature.scientific_name !== creature.name && creature.scientific_name, kind, life.state && LIFE_LABELS[life.state], `${creature.papers.length} ingested papers`].filter(Boolean).join(' · ')

    const neutral = creature.papers.length - life.support - life.opposition
    const grid = factGrid([
      ['Hypothesis', creature.hypothesis],
      ['Names tracked', creature.taxa.join(', ')],
      ['Born', life.born ? `${life.born} (${citation(creature.key_events[0].publication)})` : 'Not recorded'],
      ['Status', life.state ? `${LIFE_LABELS[life.state]}${life.died ? ` since ${life.died}` : ''}` : 'Not recorded'],
      ['Evidence', `${life.support} for · ${life.opposition} against · ${neutral} neutral`],
    ])

    const historyHeading = document.createElement('h3')
    historyHeading.textContent = 'Life of the hypothesis'
    const history = document.createElement('ol')
    history.className = 'life-history'
    for (const event of creature.key_events) {
      const item = document.createElement('li')
      const head = document.createElement('div')
      head.className = 'life-history-head'
      const year = document.createElement('span')
      year.className = 'life-history-year'
      year.textContent = String(event.publication.year)
      const stance = document.createElement('span')
      stance.className = `stance-chip side-${STANCE_INFO[event.stance].side}`
      stance.innerHTML = markerSample(event.stance)
      stance.append(STANCE_INFO[event.stance].label)
      head.append(year, stance)
      const summary = document.createElement('p')
      summary.textContent = event.opinion.summary
      item.append(head, summary, sourceLine(event.publication))
      history.append(item)
    }

    // Every ingested paper behind the count, not just the turning points.
    const all = document.createElement('details')
    all.className = 'all-papers'
    const allSummary = document.createElement('summary')
    allSummary.textContent = `All ${creature.papers.length} ingested papers`
    const list = document.createElement('ol')
    list.className = 'paper-list'
    all.addEventListener('toggle', () => {
      if (!all.open || list.childElementCount) return
      for (const paper of creature.papers) {
        const item = document.createElement('li')
        const head = document.createElement('div')
        head.className = 'life-history-head'
        const year = document.createElement('span')
        year.className = 'life-history-year'
        year.textContent = String(paper.publication.year)
        const side = document.createElement('span')
        side.className = `stance-chip side-${paper.side}`
        side.innerHTML = tickSample(paper.side)
        side.append(SIDE_LABELS[paper.side])
        head.append(year, side)
        item.append(head)
        for (const opinion of paper.opinions) {
          const line = document.createElement('p')
          line.textContent = opinion.summary
          item.append(line)
        }
        item.append(sourceLine(paper.publication))
        list.append(item)
      }
    })
    all.append(allSummary, list)
    detail.append(title, meta, grid, historyHeading, history, all)
  }
}
