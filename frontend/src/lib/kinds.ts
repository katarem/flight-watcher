/** Transportes (`app/kinds.py`): dónde vive cada uno en el panel y cómo se llama. */
import { Bus, Hotel, Plane, Ship, TrainFront, type LucideIcon } from 'lucide-react'
import { useMeta } from '@/api/queries'
import type { KindKey, KindMeta } from '@/api/types'

/** Apartado de cada transporte (el mismo que `section` en app/kinds.py). Los que aún no tienen apartado, el de vuelos. */
const SECTIONS: Partial<Record<KindKey, string>> = { flight: '/flights' }

export const KIND_ICONS: Record<KindKey, LucideIcon> = { flight: Plane, ship: Ship, train: TrainFront, bus: Bus, hotel: Hotel }

export function kindSection(kind: KindKey | null | undefined): string {
  return SECTIONS[kind ?? 'flight'] ?? '/flights'
}

/** Página de una vigilancia en el apartado de su transporte: «/flights/3», «/flights/3/edit». */
export function watchPath(kind: KindKey | null | undefined, id: number | string, suffix = ''): string {
  return `${kindSection(kind)}/${id}${suffix}`
}

/** Datos de un transporte (de /meta), con un valor razonable mientras llegan. */
export function useKind(kind: KindKey): KindMeta {
  const found = useMeta().data?.kinds.find((k) => k.key === kind)
  return found ?? {
    key: kind, label: 'Vuelos', noun: 'vuelo', plural: 'vuelos', node: 'airport', node_label: 'aeropuerto',
    section: kindSection(kind), available: true, since: '', transport: true,
  }
}
