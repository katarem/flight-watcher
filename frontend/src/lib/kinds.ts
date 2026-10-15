/** Transportes (`app/kinds.py`): cómo se llama cada uno y su icono. */
import { Bus, Hotel, Plane, Ship, TrainFront, type LucideIcon } from 'lucide-react'
import { useMeta } from '@/api/queries'
import type { KindKey, KindMeta } from '@/api/types'

export const KIND_ICONS: Record<KindKey, LucideIcon> = { flight: Plane, ship: Ship, train: TrainFront, bus: Bus, hotel: Hotel }

/** Datos de un transporte (de /meta), con un valor razonable mientras llegan. */
export function useKind(kind: KindKey): KindMeta {
  const found = useMeta().data?.kinds.find((k) => k.key === kind)
  return found ?? {
    key: kind, label: 'Vuelos', noun: 'vuelo', plural: 'vuelos', node: 'airport', node_label: 'aeropuerto',
    available: true, since: '', transport: true,
  }
}
