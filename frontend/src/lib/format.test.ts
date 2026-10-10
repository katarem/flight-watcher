import { describe, expect, it } from 'vitest'
import { fmtAgo, fmtDateTime, fmtDay, fmtPrice, fmtPriceShort, fmtShortDay } from './format'

describe('format', () => {
  it('fechas como en los avisos', () => {
    expect(fmtDay('2026-10-24')).toBe('sáb 24/10/2026')
    expect(fmtShortDay('2026-10-24')).toBe('24/10/26')
    expect(fmtDateTime('2026-10-24T08:05:00')).toBe('24/10/2026 08:05')
    expect(fmtDateTime(null)).toBe('—')
  })

  it('precios en euros con coma decimal', () => {
    expect(fmtPrice(30)).toBe('30 €')
    expect(fmtPrice(45.5)).toBe('45,50 €')
    expect(fmtPrice(null)).toBe('—')
    expect(fmtPriceShort(29.6)).toBe('30 €')
  })

  it('tiempo relativo', () => {
    const now = new Date('2026-10-10T12:00:00')
    expect(fmtAgo('2026-10-10T11:59:40', now)).toBe('ahora mismo')
    expect(fmtAgo('2026-10-10T11:30:00', now)).toBe('hace 30 min')
    expect(fmtAgo('2026-10-10T07:00:00', now)).toBe('hace 5 h')
    expect(fmtAgo('2026-10-08T12:00:00', now)).toBe('hace 2 días')
  })
})
