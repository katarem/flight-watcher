import { ArrowUpRight, CheckCircle2, Clock, TriangleAlert } from 'lucide-react'
import { Link } from 'react-router'
import { useProviders } from '@/api/queries'
import type { Alert, Run } from '@/api/types'
import { Badge, TableWrap, tableClass } from '@/components/ui/card'
import { fmtDateTime, fmtDay, fmtPrice } from '@/lib/format'

export function RunStatus({ run }: { run: Run }) {
  if (run.finished_at == null)
    return <Badge tone="accent"><Clock aria-hidden="true" /> en curso</Badge>
  if (run.ok) return <Badge tone="deal"><CheckCircle2 aria-hidden="true" /> correcta</Badge>
  return <Badge tone="danger"><TriangleAlert aria-hidden="true" /> con error</Badge>
}

export function AlertsTable({ alerts, showWatch = true }: { alerts: Alert[]; showWatch?: boolean }) {
  const provider = useProviders()
  return (
    <TableWrap label="Avisos enviados">
      <table className={tableClass}>
        <thead>
          <tr>
            <th scope="col">Enviado</th>
            {showWatch && <th scope="col">Vigilancia</th>}
            <th scope="col">Web</th>
            <th scope="col">Vuelo</th>
            <th scope="col" className="text-right!">Precio</th>
          </tr>
        </thead>
        <tbody>
          {alerts.map((a) => (
            <tr key={a.id}>
              <td className="whitespace-nowrap text-muted">{fmtDateTime(a.sent_at)}</td>
              {showWatch && (
                <td><Link to={`/watches/${a.watch_id}`} className="hover:underline">{a.watch_name}</Link></td>
              )}
              <td>{provider(a.provider).label}</td>
              <td className="whitespace-nowrap">
                {a.link ? (
                  <a href={a.link} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-0.5 text-accent hover:underline">
                    {fmtDay(a.flight_date)} <ArrowUpRight className="size-3.5" aria-hidden="true" />
                  </a>
                ) : fmtDay(a.flight_date)}
              </td>
              <td className="text-right font-semibold tabular-nums">{fmtPrice(a.price)}</td>
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
            <th scope="col">Vigilancia</th>
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
              <td><Link to={`/watches/${r.watch_id}`} className="hover:underline">{r.watch_name}</Link></td>
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
