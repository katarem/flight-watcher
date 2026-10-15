import { describe, expect, it } from 'vitest'
import { offerText } from './stays'

describe('offerText', () => {
  it('nombre, tipo, estrellas, nota, régimen y cancelación', () => {
    const types = [{ key: 'hotel', label: 'Hotel' }]
    const boards = [{ key: 'breakfast', label: 'Desayuno' }]
    expect(offerText({ name: 'Hotel Playa', type: 'hotel', stars: 4, rating: 8.6, board: 'breakfast', free_cancel: true }, types, boards))
      .toBe('Hotel Playa · hotel, 4★, nota 8,6 · desayuno · cancelación gratuita')
  })

  it('lo que la web no dice no sale', () => {
    expect(offerText({ name: 'Casa Azul' })).toBe('Casa Azul')
    expect(offerText({})).toBe('Alojamiento')
    expect(offerText(null)).toBe('')
  })
})
