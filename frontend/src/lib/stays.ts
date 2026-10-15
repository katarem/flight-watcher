/** Alojamiento (`app/stays.py`): textos de las ofertas y de los filtros con las etiquetas de /meta. */
import { useMeta } from '@/api/queries'
import type { Option, StayOfferInfo } from '@/api/types'

const label = (list: Option[] | undefined, key: string | undefined) => list?.find((o) => o.key === key)?.label ?? key ?? ''

/** «Hotel Playa · hotel, 4★, nota 8,6 · desayuno · cancelación gratuita»: una oferta en una línea. */
export function offerText(offer: StayOfferInfo | null | undefined, types?: Option[], boards?: Option[]): string {
  if (!offer) return ''
  const facts = [
    offer.type && label(types, offer.type).toLowerCase(),
    offer.stars && `${offer.stars}★`,
    offer.rating != null && `nota ${String(offer.rating).replace('.', ',')}`,
  ].filter(Boolean).join(', ')
  return [offer.name || 'Alojamiento', facts, offer.board && label(boards, offer.board).toLowerCase(),
    offer.free_cancel && 'cancelación gratuita'].filter(Boolean).join(' · ')
}

/** `offerText` con las etiquetas de /meta. */
export function useOfferText() {
  const options = useMeta().data?.stay_options
  return (offer: StayOfferInfo | null | undefined) => offerText(offer, options?.types, options?.boards)
}
