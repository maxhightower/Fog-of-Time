import type { PublicationSummary } from './types'

export function factGrid(facts: Array<[string, string]>): HTMLDListElement {
  const grid = document.createElement('dl')
  grid.className = 'fact-grid'
  for (const [label, value] of facts) {
    const dt = document.createElement('dt')
    dt.textContent = label
    const dd = document.createElement('dd')
    dd.append(value)
    grid.append(dt, dd)
  }
  return grid
}

/** "Authors. Title. Journal. doi:…" with the DOI or source as a link. */
export function sourceLine(publication: PublicationSummary): HTMLParagraphElement {
  const source = document.createElement('p')
  source.className = 'muted life-history-source'
  const { authors, title, journal, doi, url } = publication
  source.append(`${authors.join(', ')}. ${title}.${journal ? ` ${journal}.` : ''} `)
  const href = url ?? (doi ? `https://doi.org/${doi}` : null)
  if (href) {
    const link = document.createElement('a')
    link.href = href
    link.target = '_blank'
    link.rel = 'noopener noreferrer'
    link.textContent = doi ? `doi:${doi}` : 'Source'
    source.append(link)
  }
  return source
}
