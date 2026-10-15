/** URL de antes de la 2.0, cuando las vigilancias se gestionaban sueltas: /watches/… (antes de la 1.9, sale en los
 *  avisos ya enviados) y /flights/… (el apartado de vuelos de la 1.9). Desde la 2.0 una vigilancia es un tramo de un
 *  viaje: su página lleva al detalle del tramo dentro de su viaje (/trips/3/legs/7), la de editarla al formulario
 *  del viaje y la lista o «nueva» a los viajes (conservando ?origin=…&destination=…). */
import { Navigate, useLocation, useParams } from 'react-router'
import { useWatch } from '@/api/queries'
import { LoadError, PageLoading } from '@/components/ui/feedback'
import { legPath, tripPath } from '@/lib/paths'

export function LegacyWatch() {
  const { id } = useParams()
  const { pathname, search } = useLocation()
  const numeric = id != null && /^\d+$/.test(id)
  const watch = useWatch(numeric ? Number(id) : 0)
  if (!numeric) return <Navigate to={`/trips${pathname.endsWith('/new') ? '/new' : ''}${search}`} replace />
  if (watch.isPending) return <PageLoading />
  // Una que ya no existe (o de otro usuario): su «no existe».
  if (watch.isError) return <LoadError error={watch.error} />
  const { trip } = watch.data
  const target = pathname.endsWith('/edit') ? tripPath(trip.id, '/edit') : legPath(trip.id, watch.data.watch.id)
  return <Navigate to={`${target}${search}`} replace />
}
