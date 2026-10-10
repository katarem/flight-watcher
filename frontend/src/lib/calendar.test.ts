import { describe, expect, it } from 'vitest'
import { buildCalendar, type CalendarPrice } from './calendar'

const row = (date: string, price: number, provider = 'vueling', deal: string | null = null): CalendarPrice => ({
  provider, flight_date: date, price, route: null, link: `https://x/${date}`, deal,
})

describe('buildCalendar', () => {
  it('sin precios no hay meses', () => {
    expect(buildCalendar([])).toEqual([])
  })

  it('arma semanas de lunes a domingo y cubre todos los meses intermedios', () => {
    const months = buildCalendar([row('2026-10-01', 50), row('2026-12-31', 20)])
    expect(months.map((m) => m.label)).toEqual(['octubre 2026', 'noviembre 2026', 'diciembre 2026'])
    const oct = months[0]
    // 1/10/2026 es jueves: lunes a miércoles vacíos.
    expect(oct.weeks[0].slice(0, 3)).toEqual([null, null, null])
    expect(oct.weeks[0][3]?.day).toBe(1)
    expect(oct.weeks.every((w) => w.length === 7)).toBe(true)
    const days = oct.weeks.flat().filter(Boolean)
    expect(days).toHaveLength(31)
    expect(months[1].weeks.flat().filter(Boolean)).toHaveLength(30)
  })

  it('ordena los precios del día y asigna nivel por cuartil y chollo', () => {
    const months = buildCalendar([
      row('2026-10-05', 90), row('2026-10-05', 30, 'ryanair', 'fixed'),
      row('2026-10-06', 60), row('2026-10-07', 80), row('2026-10-08', 120),
    ])
    const days = months[0].weeks.flat().filter((d) => d && d.prices.length)
    const byDate = Object.fromEntries(days.map((d) => [d!.date, d!]))
    expect(byDate['2026-10-05'].prices.map((p) => p.price)).toEqual([30, 90])
    expect(byDate['2026-10-05'].deal).toBe(true)
    expect(byDate['2026-10-05'].level).toBe(1)
    expect(byDate['2026-10-08'].level).toBe(3) // mismo criterio de cuartiles que tenía el servidor
    expect(byDate['2026-10-06'].deal).toBe(false)
  })
})
