/** Calendario de precios del detalle: meses → semanas (lunes a domingo) → días. */
import { MESES, isoDay, parseDay } from './format'

export interface CalendarPrice {
  provider: string
  flight_date: string
  price: number
  route: string | null
  link: string
  deal: string | null
}

export interface CalendarDay {
  day: number
  date: string
  prices: CalendarPrice[]
  /** 1 = de los más baratos … 4 = de los más caros (cuartil del mínimo del día); 0 = sin precio. */
  level: number
  deal: boolean
}

export interface CalendarMonth {
  key: string
  label: string
  weeks: (CalendarDay | null)[][]
}

export function buildCalendar(rows: CalendarPrice[]): CalendarMonth[] {
  const byDay = new Map<string, CalendarPrice[]>()
  for (const r of rows) {
    const key = r.flight_date.slice(0, 10)
    byDay.set(key, [...(byDay.get(key) ?? []), r])
  }
  if (!byDay.size) return []
  for (const list of byDay.values()) list.sort((a, b) => a.price - b.price)

  const mins = [...byDay.values()].map((l) => l[0].price).sort((a, b) => a - b)
  const cuts = [0.25, 0.5, 0.75].map((q) => mins[Math.min(mins.length - 1, Math.floor(mins.length * q))])
  const keys = [...byDay.keys()].sort()
  const first = parseDay(keys[0])
  const last = parseDay(keys[keys.length - 1])

  const months: CalendarMonth[] = []
  for (let cur = new Date(first.getFullYear(), first.getMonth(), 1); cur <= last; cur = new Date(cur.getFullYear(), cur.getMonth() + 1, 1)) {
    const y = cur.getFullYear()
    const m = cur.getMonth()
    const d = new Date(y, m, 1 - ((cur.getDay() + 6) % 7)) // lunes de la primera semana
    const weeks: (CalendarDay | null)[][] = []
    do {
      const week: (CalendarDay | null)[] = []
      for (let i = 0; i < 7; i++, d.setDate(d.getDate() + 1)) {
        if (d.getMonth() !== m) {
          week.push(null)
          continue
        }
        const date = isoDay(d)
        const prices = byDay.get(date) ?? []
        week.push({
          day: d.getDate(),
          date,
          prices,
          level: prices.length ? 1 + cuts.filter((c) => prices[0].price > c).length : 0,
          deal: prices.some((p) => p.deal),
        })
      }
      weeks.push(week)
    } while (d.getMonth() === m)
    months.push({ key: `${y}-${m + 1}`, label: `${MESES[m]} ${y}`, weeks })
  }
  return months
}
