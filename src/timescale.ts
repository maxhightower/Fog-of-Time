// Geologic time scale used for the reference bands on the timeline.
// Boundaries follow the ICS International Chronostratigraphic Chart (v2023/09+),
// matching the conversions used by the extraction records (e.g. Cretaceous base
// ~143.1 Ma, Albian base 113.2 Ma). Stages are listed for the Mesozoic only.

export type GeoRank = 'period' | 'epoch' | 'stage'

export interface GeoUnit {
  name: string
  abbr: string
  rank: GeoRank
  /** Older boundary (base), Ma. */
  start: number
  /** Younger boundary (top), Ma. */
  end: number
  /** ICS period colour the unit belongs to. */
  color: string
}

const PERIODS: Array<[string, string, number, number, string]> = [
  ['Ediacaran', 'Ed', 635, 538.8, '#FED96A'],
  ['Cambrian', 'Є', 538.8, 486.85, '#7FA056'],
  ['Ordovician', 'O', 486.85, 443.8, '#009270'],
  ['Silurian', 'S', 443.8, 419.2, '#B3E1B6'],
  ['Devonian', 'D', 419.2, 358.9, '#CB8C37'],
  ['Carboniferous', 'C', 358.9, 298.9, '#67A599'],
  ['Permian', 'P', 298.9, 251.902, '#F04028'],
  ['Triassic', 'T', 251.902, 201.4, '#812B92'],
  ['Jurassic', 'J', 201.4, 143.1, '#34B2C9'],
  ['Cretaceous', 'K', 143.1, 66, '#7FC64E'],
  ['Paleogene', 'Pg', 66, 23.04, '#FD9A52'],
  ['Neogene', 'N', 23.04, 2.58, '#FFE619'],
  ['Quaternary', 'Q', 2.58, 0, '#F9F97F'],
]

const EPOCHS: Array<[string, string, number, number]> = [
  ['Terreneuvian', 'Tn', 538.8, 521],
  ['Series 2', 'S2', 521, 506.5],
  ['Miaolingian', 'Mi', 506.5, 497],
  ['Furongian', 'Fu', 497, 486.85],
  ['Early Ordovician', 'EO', 486.85, 471.3],
  ['Middle Ordovician', 'MO', 471.3, 458.2],
  ['Late Ordovician', 'LO', 458.2, 443.8],
  ['Llandovery', 'Ll', 443.8, 433.4],
  ['Wenlock', 'We', 433.4, 427.4],
  ['Ludlow', 'Lu', 427.4, 423],
  ['Přídolí', 'Př', 423, 419.2],
  ['Early Devonian', 'ED', 419.2, 393.3],
  ['Middle Devonian', 'MD', 393.3, 382.7],
  ['Late Devonian', 'LD', 382.7, 358.9],
  ['Mississippian', 'Mis', 358.9, 323.2],
  ['Pennsylvanian', 'Pen', 323.2, 298.9],
  ['Cisuralian', 'Ci', 298.9, 273.01],
  ['Guadalupian', 'Gu', 273.01, 259.51],
  ['Lopingian', 'Lo', 259.51, 251.902],
  ['Early Triassic', 'ET', 251.902, 247.2],
  ['Middle Triassic', 'MT', 247.2, 237],
  ['Late Triassic', 'LT', 237, 201.4],
  ['Early Jurassic', 'EJ', 201.4, 174.7],
  ['Middle Jurassic', 'MJ', 174.7, 161.5],
  ['Late Jurassic', 'LJ', 161.5, 143.1],
  ['Early Cretaceous', 'EK', 143.1, 100.5],
  ['Late Cretaceous', 'LK', 100.5, 66],
  ['Paleocene', 'Pal', 66, 56],
  ['Eocene', 'Eo', 56, 33.9],
  ['Oligocene', 'Ol', 33.9, 23.04],
  ['Miocene', 'Mio', 23.04, 5.333],
  ['Pliocene', 'Pli', 5.333, 2.58],
  ['Pleistocene', 'Ple', 2.58, 0.0117],
  ['Holocene', 'H', 0.0117, 0],
]

const STAGES: Array<[string, string, number, number]> = [
  ['Induan', 'Ind', 251.902, 251.2],
  ['Olenekian', 'Ole', 251.2, 247.2],
  ['Anisian', 'Ani', 247.2, 242],
  ['Ladinian', 'Lad', 242, 237],
  ['Carnian', 'Car', 237, 227],
  ['Norian', 'Nor', 227, 208.5],
  ['Rhaetian', 'Rha', 208.5, 201.4],
  ['Hettangian', 'Het', 201.4, 199.5],
  ['Sinemurian', 'Sin', 199.5, 192.9],
  ['Pliensbachian', 'Pli', 192.9, 184.2],
  ['Toarcian', 'Toa', 184.2, 174.7],
  ['Aalenian', 'Aal', 174.7, 170.9],
  ['Bajocian', 'Baj', 170.9, 168.2],
  ['Bathonian', 'Bat', 168.2, 165.3],
  ['Callovian', 'Cal', 165.3, 161.5],
  ['Oxfordian', 'Oxf', 161.5, 154.8],
  ['Kimmeridgian', 'Kim', 154.8, 149.2],
  ['Tithonian', 'Tith', 149.2, 143.1],
  ['Berriasian', 'Ber', 143.1, 137.05],
  ['Valanginian', 'Val', 137.05, 132.6],
  ['Hauterivian', 'Hau', 132.6, 125.77],
  ['Barremian', 'Bar', 125.77, 121.4],
  ['Aptian', 'Apt', 121.4, 113.2],
  ['Albian', 'Alb', 113.2, 100.5],
  ['Cenomanian', 'Cen', 100.5, 93.9],
  ['Turonian', 'Tur', 93.9, 89.8],
  ['Coniacian', 'Con', 89.8, 86.3],
  ['Santonian', 'San', 86.3, 83.6],
  ['Campanian', 'Cam', 83.6, 72.1],
  ['Maastrichtian', 'Maa', 72.1, 66],
]

function periodColorAt(age: number): string {
  const period = PERIODS.find(([, , start, end]) => age <= start && age > end) ?? PERIODS[PERIODS.length - 1]
  return period[4]
}

export const TIMESCALE: Record<GeoRank, GeoUnit[]> = {
  period: PERIODS.map(([name, abbr, start, end, color]) => ({ name, abbr, rank: 'period', start, end, color })),
  epoch: EPOCHS.map(([name, abbr, start, end]) => ({ name, abbr, rank: 'epoch', start, end, color: periodColorAt((start + end) / 2) })),
  stage: STAGES.map(([name, abbr, start, end]) => ({ name, abbr, rank: 'stage', start, end, color: periodColorAt((start + end) / 2) })),
}

export const TIMESCALE_OLDEST = PERIODS[0][2]

export const PRESETS: Array<{ label: string; from: number; to: number }> = [
  { label: '500 Myr', from: 500, to: 0 },
  { label: 'Mesozoic', from: 251.902, to: 66 },
  { label: 'Triassic', from: 251.902, to: 201.4 },
  { label: 'Jurassic', from: 201.4, to: 143.1 },
  { label: 'Cretaceous', from: 143.1, to: 66 },
]
