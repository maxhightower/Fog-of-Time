import type { TimelineEvidence } from './types'

// Hand-curated common names and nicknames used only for searching and filtering.
// They are not extracted from the paper corpus, so they are never displayed as
// facts about a record. Keep entries conservative: add a name only when it is in
// widespread, unambiguous use for that taxon or specimen.

/** Common names keyed by the exact taxon name used in the dataset. */
const TAXON_NAMES: Record<string, string[]> = {
  'Tyrannosaurus rex': ['T. rex', 'T-rex', 'tyrannosaur', 'tyrant lizard king'],
  'Albertosaurus sarcophagus': ['tyrannosaur'],
  'Daspletosaurus sp.': ['tyrannosaur'],
  'Gorgosaurus sp.': ['tyrannosaur'],
  'Nanuqsaurus hoglundi': ['tyrannosaur'],
  'Tyrannosaurid sp. indet.': ['tyrannosaur'],
  'Anzu wyliei': ['chicken from hell'],
  'Microraptor': ['raptor', 'feathered dinosaur'],
  'Sinornithosaurus': ['raptor', 'feathered dinosaur'],
  'Anchiornis huxleyi': ['feathered dinosaur'],
  'Beipiaosaurus': ['feathered dinosaur', 'therizinosaur'],
  'Confuciusornis': ['bird', 'early bird'],
  'Diamantinasaurus matildae': ['titanosaur', 'sauropod', 'long-necked dinosaur'],
  'Titanosauria indet.': ['titanosaur', 'sauropod', 'long-necked dinosaur'],
  'Wintonotitan wattsi': ['sauropod', 'long-necked dinosaur'],
  'Tenontosaurus tilletti': ['ornithopod'],
  'Convolosaurus marri': ['ornithopod'],
}

/**
 * Specimen nicknames keyed by a compact specimen number (letters and digits
 * only), matched against each record's specimen label and physical key.
 */
const SPECIMEN_NICKNAMES: Record<string, string[]> = {
  fmnhpr2081: ['Sue'],
  mor980: ["Peck's Rex"],
  mor1125: ['B-rex'],
  aodf603: ['Matilda'],
  aodf604: ['Banjo'],
}

export function normalizeName(value: string): string {
  return value
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()
}

function compact(value: string): string {
  return normalizeName(value).replaceAll(' ', '')
}

export function namesFor(record: TimelineEvidence): string[] {
  const names = [...(TAXON_NAMES[record.taxon] ?? [])]
  const identifiers = compact(`${record.specimen_label ?? ''} ${record.physical_key}`)
  for (const [specimen, nicknames] of Object.entries(SPECIMEN_NICKNAMES)) {
    if (identifiers.includes(specimen)) names.push(...nicknames)
  }
  return names
}

/** Words a name search matches against: taxon, specimen label, common names and nicknames. */
export function searchWords(record: TimelineEvidence): string[] {
  return normalizeName([record.taxon, record.specimen_label ?? '', ...namesFor(record)].join(' ')).split(' ')
}

/**
 * Every word of the query must start a word of the record's names, so "raptor"
 * finds Microraptor's "raptor" alias but not Siamraptor, while "siam" still
 * finds Siamraptor.
 */
export function matchesName(words: string[], query: string): boolean {
  const terms = normalizeName(query).split(' ').filter(Boolean)
  return terms.every(term => words.some(word => word.startsWith(term)))
}

/** Suggestions for the name search: each distinct name with the taxa it points to. */
export function nameSuggestions(records: TimelineEvidence[]): Array<{ value: string; hint: string }> {
  const taxaByName = new Map<string, Set<string>>()
  for (const record of records) {
    for (const name of [record.taxon, ...namesFor(record)]) {
      if (!taxaByName.has(name)) taxaByName.set(name, new Set())
      taxaByName.get(name)!.add(record.taxon)
    }
  }
  return [...taxaByName.entries()]
    .map(([value, taxa]) => ({ value, hint: taxa.has(value) ? '' : [...taxa].sort().join(', ') }))
    .sort((a, b) => a.value.localeCompare(b.value))
}
