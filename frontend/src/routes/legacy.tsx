/** URL de antes de la 1.9 (/watches/…): salen en los avisos ya enviados y en marcadores. Llevan al apartado del
 *  transporte de la vigilancia (/flights/…), conservando lo que venga detrás (?origin=…&for_trip=…). */
import { Navigate, useLocation, useParams } from 'react-router'
import { useWatch } from '@/api/queries'
import { PageLoading } from '@/components/ui/feedback'
import { kindSection, watchPath } from '@/lib/kinds'

export function LegacyWatch() {
  const { id } = useParams()
  const { pathname, search } = useLocation()
  const numeric = id != null && /^\d+$/.test(id)
  const watch = useWatch(numeric ? Number(id) : 0)
  if (numeric && watch.isPending) return <PageLoading />
  const rest = pathname.replace(/^\/watches/, '')
  // Sin vigilancia (o una que ya no existe), el apartado de vuelos: allí sale su «no existe» si hace falta.
  const target = numeric && watch.data
    ? watchPath(watch.data.watch.kind, watch.data.watch.id, rest.replace(/^\/\d+/, ''))
    : `${kindSection('flight')}${rest}`
  return <Navigate to={`${target}${search}`} replace />
}
