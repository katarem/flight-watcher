import { describe, expect, it } from 'vitest'
import { fmtAgo, fmtDateTime, fmtDay, fmtMoney, fmtPrice, fmtPriceShort, fmtShortDay, priceExtras, stopsRule } from './format'

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

  it('otras monedas y escalas', () => {
    expect(fmtMoney(12000, 'HUF')).toBe('12.000 HUF')
    expect(fmtMoney(1234.5, 'GBP')).toBe('1.234,50 GBP')
    expect(priceExtras({ currency: 'HUF', orig_price: 12000, stops: 1 })).toBe('12.000 HUF · 1 escala')
    expect(priceExtras({ currency: 'EUR', orig_price: null, stops: 0 })).toBe('')
    expect(stopsRule(0)).toBe('solo directos')
    expect(stopsRule(2)).toBe('hasta 2 escalas')
    expect(stopsRule(null)).toBe('con o sin escalas')
  })
})
