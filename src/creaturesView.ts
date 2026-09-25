import type { CorpusState, CreaturePaper, KeyEvent, PublicationSummary, Side, Stance, StateChange, TaxonomicOpinion, TheoreticalCreature } from './types'
import {
  AUTHORITY_LABELS, citation, LIFE_EXPLANATIONS, LIFE_LABELS, lifeOf, Lifelines, markerSample, SIDE_LABELS, STANCE_INFO,
  STRENGTH_LABELS, tickSample, type Life, type LifeState, type SourcedClaim,
} from './creatures'
import { factGrid, sourceLine } from './dom'

const THIS_YEAR = new Date().getFullYear()
/** Rows drawn on the lifeline chart before "Show all" is needed. */
const ROW_LIMIT = 40
const PLAY_STEP_MS = 120

type Show = 'all' | 'theoretical' | 'official' | 'in_use' | 'contested' | 'sunk'
type Sort = 'papers' | 'name' | 'born' | 'eventful'

const SHOW_OPTIONS: Array<{ value: Show; label: string; title: string }> = [
  { value: 'all', label: 'All', title: 'Every tracked creature' },
  { value: 'theoretical', label: 'Curated', title: 'Hypotheses with hand-curated turning points, such as the American cheetah' },
  { value: 'official', label: 'Rule-based', title: 'Every genus and species the corpus reports fossils of, with turning points chosen by a written rule' },
  { value: 'in_use', label: 'In use', title: LIFE_EXPLANATIONS.in_use },
  { value: 'contested', label: 'Contested', title: LIFE_EXPLANATIONS.contested },
  { value: 'sunk', label: 'Sunk', title: LIFE_EXPLANATIONS.sunk },
]

const SORT_OPTIONS: Array<{ value: Sort; label: string }> = [
  { value: 'papers', label: 'Most papers' },
  { value: 'eventful', label: 'Most turning points' },
  { value: 'born', label: 'First proposed' },
  { value: 'name', label: 'Name' },
]

const LIFE_STATES: LifeState[] = ['in_use', 'contested', 'sunk']
const STANCE_ORDER: Stance[] = ['proposes', 'recorded', 'supports', 'revives', 'challenges', 'refutes']
const SIDES: Side[] = ['for', 'against', 'neutral', 'usage']

interface RawKeyEvent { stance: Stance; publication_id: string; opinion: TaxonomicOpinion; rationale?: string | null }
interface RawPaper { publication_id: string; side: Side; opinions: TaxonomicOpinion[] }
interface RawState { year: number; state: CorpusState; cause: StateChange['cause']; opinion_id: string; publication_id: string }
interface RawCreature extends Omit<TheoreticalCreature, 'key_events' | 'papers' | 'states'> { key_events: RawKeyEvent[]; papers: RawPaper[]; states: RawState[] }
interface CreatureExport { publications: Record<string, PublicationSummary>; creatures: RawCreature[] }

/** The export stores each publication once; creatures refer to it by id. */
function hydrate(data: CreatureExport): TheoreticalCreature[] {
  const publication = (id: string) => data.publications[id]
  return data.creatures.map(creature => ({
    ...creature,
    key_events: creature.key_events.map((event): KeyEvent => ({ stance: event.stance, opinion: event.opinion, rationale: event.rationale, publication: publication(event.publication_id) })),
    papers: creature.papers.map((paper): CreaturePaper => ({ side: paper.side, opinions: paper.opinions, publication: publication(paper.publication_id) })),
    states: creature.states.map((change): StateChange => ({ year: change.year, state: change.state, cause: change.cause, opinion_id: change.opinion_id, publication: publication(change.publication_id) })),
  }))
}

/** "Stated with evidence · recorded by a PBDB compiler · pbdb-opinion:123". */
function provenance(claim: TaxonomicOpinion): string {
  const records = claim.source_records.length ? claim.source_records.join(', ') : claim.id
  return [STRENGTH_LABELS[claim.strength], AUTHORITY_LABELS[claim.authority], claim.derivation_rule && `rule ${claim.derivation_rule}`, records]
    .filter(Boolean)
    .join(' · ')
}

/** The paper's own wording of the name, when it differs from the tracked one. */
function asPublished(claim: TaxonomicOpinion): string {
  const differs = claim.name_as_published !== claim.taxon && !claim.summary.includes(claim.name_as_published)
  return differs ? `Published as ${claim.name_as_published}. ` : ''
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
            <p class="layer-note">Count = ingested papers with a claim on the creature (▲ for · ▼ against · ○ only reported fossils under the name). A count is not a measure of consensus.</p>
          </section>
        </aside>

        <main class="main-column">
          <section class="creatures-card" aria-labelledby="creatures-heading">
            <div class="section-heading">
              <div>
                <p class="eyebrow">CREATURES</p>
                <h2 id="creatures-heading">Lives of creatures in the literature</h2>
              </div>
              <p class="muted">Every creature is a hypothesis argued over in the ingested papers. States describe what the corpus looked like at the time (in use, contested, sunk), not which side is right. Rule-based creatures follow a written rule; curated ones have hand-picked turning points.</p>
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
        this.el.status.textContent = `${this.creatures.length} creatures · ${curated} curated, ${this.creatures.length - curated} rule-based`
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
    // The detail panel replays to the same year as the chart: nothing published later may show.
    const selected = this.creatures.find(creature => creature.id === this.selected)
    if (selected) this.showDetail(selected)
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
          case 'official': return !creature.curated
          case 'all': return true
          default: return life.state === this.show
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
      button.setAttribute('aria-label', `${creature.name}, ${life.state ? LIFE_LABELS[life.state] : 'not yet proposed'}, ${life.papers.length} papers: ${life.support} for, ${life.opposition} against, ${life.usage} only using the name`)

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
      detail.textContent = creature.curated ? `${creature.scientific_name ?? ''} · curated` : creature.rank ?? ''
      names.append(name, detail)
      const count = document.createElement('span')
      count.className = 'creature-count'
      count.innerHTML = `<strong>${life.papers.length}</strong><span class="creature-split" title="for · against · name used only">▲${life.support} ▼${life.opposition} ○${life.usage}</span>`
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
    const year = Number(this.el.slider.value)
    const latestYear = Number(this.el.slider.max)
    const life = lifeOf(creature, year, THIS_YEAR)
    const title = document.createElement('h2')
    title.id = 'creature-detail-heading'
    title.textContent = creature.name

    const meta = document.createElement('p')
    meta.className = 'detail-meta'
    const kind = creature.curated ? 'Curated turning points' : 'Rule-based turning points'
    const asOf = year >= latestYear ? 'whole corpus' : `known by ${year}`
    meta.textContent = [creature.scientific_name !== creature.name && creature.scientific_name, kind, asOf, `${life.papers.length} of ${creature.papers.length} ingested papers`].filter(Boolean).join(' · ')

    if (life.state === null) {
      const note = document.createElement('p')
      note.className = 'muted'
      note.textContent = `No ingested paper had made this claim by ${year}. Move "Known by" later to see its history.`
      detail.append(title, meta, note)
      return
    }

    const neutral = life.papers.length - life.support - life.opposition - life.usage
    const cause = life.change
    const stateText = `${LIFE_LABELS[life.state]} since ${life.since}` + (cause
      ? ` — ${cause.cause === 'turning_point' ? 'turning point' : 'opposing claim'}: ${citation(cause.publication)}`
      : '')
    const grid = factGrid([
      ['Hypothesis', creature.hypothesis],
      ['Tracked names', `${creature.taxa.join(', ')} (normalized labels, not necessarily what the papers wrote)`],
      ['Published as', life.names.map(use => `${use.name} (${use.first === use.last ? use.first : `${use.first}–${use.last}`}, ${use.papers} ${use.papers === 1 ? 'paper' : 'papers'})`).join('; ')],
      ['Corpus state', stateText],
      ['What that means', LIFE_EXPLANATIONS[life.state]],
      ['Papers', `${life.support} for · ${life.opposition} against · ${neutral} neutral · ${life.usage} only reported fossils under the name`],
      ['Turning points', creature.curated ? `curated in ${creature.turning_points}` : `rule ${creature.turning_points}`],
      ['State rule', creature.state_rule],
    ])

    // Competing claims side by side, so disagreement stays visible instead of being settled by a badge.
    const competingHeading = document.createElement('h3')
    competingHeading.textContent = `Competing claims ${year >= latestYear ? 'in the corpus' : `as of ${year}`}`
    const competing = document.createElement('div')
    competing.className = 'competing-claims'
    competing.append(
      this.claimCard('Latest claim for the hypothesis', life.latestFor, 'for'),
      this.claimCard('Latest claim against it', life.latestAgainst, 'against'),
    )

    const historyHeading = document.createElement('h3')
    historyHeading.textContent = 'Turning points'
    const history = document.createElement('ol')
    history.className = 'life-history'
    for (const event of life.events) {
      const item = document.createElement('li')
      const head = document.createElement('div')
      head.className = 'life-history-head'
      const eventYear = document.createElement('span')
      eventYear.className = 'life-history-year'
      eventYear.textContent = String(event.publication.year)
      const stance = document.createElement('span')
      stance.className = `stance-chip side-${STANCE_INFO[event.stance].side}`
      stance.innerHTML = markerSample(event.stance)
      stance.append(STANCE_INFO[event.stance].label)
      head.append(eventYear, stance)
      const summary = document.createElement('p')
      summary.textContent = asPublished(event.opinion) + event.opinion.summary
      item.append(head, summary)
      if (event.rationale) {
        const rationale = document.createElement('p')
        rationale.className = 'claim-provenance'
        rationale.textContent = `Curator's rationale: ${event.rationale}`
        item.append(rationale)
      }
      item.append(this.provenanceLine(event.opinion), sourceLine(event.publication))
      history.append(item)
    }
    const hidden = creature.key_events.length - life.events.length
    if (hidden > 0) {
      const note = document.createElement('li')
      note.className = 'muted'
      note.textContent = `${hidden} later turning ${hidden === 1 ? 'point is' : 'points are'} hidden until "Known by" reaches ${creature.key_events[life.events.length].publication.year}.`
      history.append(note)
    }

    // Every ingested paper behind the count, not just the turning points.
    const all = document.createElement('details')
    all.className = 'all-papers'
    const allSummary = document.createElement('summary')
    allSummary.textContent = `All ${life.papers.length} ingested papers${year >= latestYear ? '' : ` up to ${year}`}`
    const list = document.createElement('ol')
    list.className = 'paper-list'
    all.addEventListener('toggle', () => {
      if (!all.open || list.childElementCount) return
      for (const paper of life.papers) {
        const item = document.createElement('li')
        const head = document.createElement('div')
        head.className = 'life-history-head'
        const paperYear = document.createElement('span')
        paperYear.className = 'life-history-year'
        paperYear.textContent = String(paper.publication.year)
        const side = document.createElement('span')
        side.className = `stance-chip side-${paper.side}`
        side.innerHTML = tickSample(paper.side)
        side.append(SIDE_LABELS[paper.side])
        head.append(paperYear, side)
        item.append(head)
        for (const opinion of paper.opinions) {
          const line = document.createElement('p')
          line.textContent = asPublished(opinion) + opinion.summary
          line.title = provenance(opinion)
          item.append(line)
        }
        item.append(sourceLine(paper.publication))
        list.append(item)
      }
    })
    all.append(allSummary, list)
    detail.append(title, meta, grid, competingHeading, competing, historyHeading, history, all)
  }

  private claimCard(heading: string, sourced: SourcedClaim | null, side: Side): HTMLElement {
    const card = document.createElement('section')
    card.className = `claim-card side-${side}`
    const title = document.createElement('h4')
    title.textContent = heading
    card.append(title)
    if (!sourced) {
      const none = document.createElement('p')
      none.className = 'muted'
      none.textContent = 'No stated claim on this side in the ingested papers so far.'
      card.append(none)
      return card
    }
    const { claim, publication } = sourced
    const what = document.createElement('p')
    what.innerHTML = ''
    const reported = document.createElement('strong')
    reported.textContent = claim.name_as_published
    what.append('Reported as ', reported, ` · ${citation(publication)}`)
    const summary = document.createElement('p')
    summary.textContent = claim.summary
    card.append(what, summary, this.provenanceLine(claim), sourceLine(publication))
    return card
  }

  private provenanceLine(claim: TaxonomicOpinion): HTMLParagraphElement {
    const line = document.createElement('p')
    line.className = 'claim-provenance'
    line.textContent = provenance(claim)
    return line
  }
}
