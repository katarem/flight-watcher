import { CheckCircle2, Clock, TriangleAlert } from 'lucide-react'
import { Link } from 'react-router'
import { useProviders } from '@/api/queries'
import type { Run, TripAlert } from '@/api/types'
import { Badge, TableWrap, tableClass } from '@/components/ui/card'
import { fmtDateTime, fmtDay, fmtPrice } from '@/lib/format'
import { legPath, tripPath } from '@/lib/paths'

export function RunStatus({ run }: { run: Run }) {
  if (run.finished_at == null)
    return <Badge tone="accent"><Clock aria-hidden="true" /> en curso</Badge>
  if (run.ok) return <Badge tone="deal"><CheckCircle2 aria-hidden="true" /> correcta</Badge>
  return <Badge tone="danger"><TriangleAlert aria-hidden="true" /> con error</Badge>
}

/** Avisos enviados de un viaje o, con `showTrip`, de todos los viajes del usuario. */
export function AlertsTable({ alerts, showTrip = true }: { alerts: (TripAlert & { trip_name?: string })[]; showTrip?: boolean }) {
  return (
    <TableWrap label="Avisos enviados">
      <table className={tableClass}>
        <thead>
          <tr>
            <th scope="col">Enviado</th>
            {showTrip && <th scope="col">Viaje</th>}
            <th scope="col">Fechas</th>
            <th scope="col" className="text-right!">Precio</th>
          </tr>
        </thead>
        <tbody>
          {alerts.map((a) => (
            <tr key={a.id}>
              <td className="whitespace-nowrap text-muted">{fmtDateTime(a.sent_at)}</td>
              {showTrip && (
                <td><Link to={tripPath(a.trip_id)} className="hover:underline">{a.trip_name}</Link></td>
              )}
              <td className="whitespace-nowrap">
                {fmtDay(a.out_date)}{a.ret_date && <> → {fmtDay(a.ret_date)}</>}
              </td>
              <td className="text-right font-semibold tabular-nums">{fmtPrice(a.total)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </TableWrap>
  )
}

export function RunsTable({ runs, full }: { runs: Run[]; full?: boolean }) {
  const provider = useProviders()
  return (
    <TableWrap label="Ejecuciones">
      <table className={tableClass}>
        <thead>
          <tr>
            <th scope="col">Inicio</th>
            {full && <th scope="col">Viaje</th>}
            <th scope="col">Tramo</th>
            <th scope="col">Web</th>
            {full && <th scope="col">Origen</th>}
            <th scope="col">Estado</th>
            <th scope="col" className="text-right!">Fechas</th>
            {full && <th scope="col" className="text-right!">Chollos</th>}
            {full && <th scope="col">Detalle</th>}
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.id}>
              <td className="whitespace-nowrap text-muted">{fmtDateTime(r.started_at)}</td>
              {full && <td><Link to={tripPath(r.trip_id)} className="hover:underline">{r.trip_name}</Link></td>}
              <td><Link to={legPath(r.trip_id, r.watch_id)} className="hover:underline">{r.watch_name}</Link></td>
              <td>{provider(r.provider).label}</td>
              {full && <td className="text-muted">{r.trigger === 'cron' ? 'automática' : 'manual'}</td>}
              <td><RunStatus run={r} /></td>
              <td className="text-right tabular-nums">{r.n_prices}</td>
              {full && <td className="text-right tabular-nums">{r.n_deals}</td>}
              {full && <td className="max-w-md text-xs text-muted">{r.error}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </TableWrap>
  )
}
