import { Luggage, Plus, Sparkles } from 'lucide-react'
import { Link } from 'react-router'
import { useAlerts, useMeta, useRuns, useTrips } from '@/api/queries'
import type { TripCard } from '@/api/types'
import { buttonClass } from '@/components/ui/button'
import { Badge, Card, CardHeader, PageHeader, TableWrap, tableClass } from '@/components/ui/card'
import { EmptyState, LoadError, PageLoading } from '@/components/ui/feedback'
import { ComboParts, comboDates as datesOf, TripPill } from '@/components/trip/parts'
import { AlertsTable, RunsTable } from '@/components/watch/tables'
import { fmtPrice } from '@/lib/format'
import { useTitle } from '@/lib/hooks'
import { tripPath } from '@/lib/paths'

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`

/** Una cifra del resumen (cuántos viajes, cuántos con chollo, el más barato). */
function Stat({ id, label, value, detail }: { id: string; label: string; value: React.ReactNode; detail?: React.ReactNode }) {
  return (
    <Card aria-labelledby={id} className="flex flex-col gap-1">
      <h2 id={id} className="text-sm font-medium text-muted">{label}</h2>
      <p className="text-2xl font-semibold tracking-tight tabular-nums">{value}</p>
      {detail && <p className="text-sm text-muted">{detail}</p>}
    </Card>
  )
}

/** Fechas de la mejor combinación de un viaje. */
const comboDates = (t: TripCard) => datesOf(t.best!)

/** Los chollos de ahora mismo: la combinación más barata de cada viaje que cumple sus reglas de aviso. */
function CurrentDeals({ trips }: { trips: TripCard[] }) {
  const rows = trips.filter((t) => t.best?.deal).sort((a, b) => a.best!.total - b.best!.total).slice(0, 8)
  if (!rows.length) return <p className="text-sm text-muted">Ninguno de tus viajes tiene ahora un precio de chollo.</p>
  return (
    <TableWrap label="Chollos ahora">
      <table className={tableClass}>
        <thead>
          <tr>
            <th scope="col">Viaje</th>
            <th scope="col">Fechas</th>
            <th scope="col">Desglose</th>
            <th scope="col" className="text-right!">Precio</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((t) => (
            <tr key={t.id}>
              <td>
                <span className="flex flex-wrap items-center gap-2">
                  <Link to={tripPath(t.id)} className="hover:underline">{t.name}</Link>
                  <TripPill trip={t} />
                </span>
              </td>
              <td className="whitespace-nowrap">{comboDates(t)}</td>
              <td><ComboParts combo={t.best!} /></td>
              <td className="text-right font-semibold whitespace-nowrap tabular-nums">{fmtPrice(t.best!.total)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </TableWrap>
  )
}

export function DashboardPage() {
  useTitle('Panel')
  const meta = useMeta().data
  const trips = useTrips()
  const alerts = useAlerts(8)
  const runs = useRuns(8)

  if (trips.isPending) return <PageLoading />
  if (trips.isError) return <LoadError error={trips.error} />
  const list = trips.data
  const soon = (meta?.kinds ?? []).filter((k) => !k.available && k.since).sort((a, b) => a.since.localeCompare(b.since))
  const priced = list.filter((t) => t.best).sort((a, b) => a.best!.total - b.best!.total)
  const cheapest = priced[0]
  const deals = list.filter((t) => t.best?.deal).length
  const roundTrips = list.filter((t) => t.return).length
  const stayOnly = list.filter((t) => !t.outbound).length
  const oneWay = list.length - roundTrips - stayOnly

  return (
    <>
      <PageHeader
        title="Panel"
        description="Resumen de tus viajes: el más barato, los chollos de ahora y los últimos avisos."
        actions={<Link to="/trips/new" className={buttonClass()}><Plus /> Nuevo viaje</Link>}
      />

      {list.length === 0 ? (
        <EmptyState
          icon={<Luggage />}
          title="Aún no vigilas ningún viaje"
          action={<Link to="/trips/new" className={buttonClass()}><Plus /> Crear el primero</Link>}
        >
          Elige la ida (y la vuelta), el alojamiento o los dos, y te avisamos cuando el viaje baje de lo que marques o
          de lo habitual.
        </EmptyState>
      ) : (
        <div className="grid gap-4 sm:grid-cols-3">
          <Stat
            id="resumen-viajes" label="Viajes" value={list.length}
            detail={
              <>
                {[roundTrips && `${roundTrips} de ida y vuelta`, oneWay && `${oneWay} solo ida`,
                  stayOnly && `${stayOnly} solo alojamiento`].filter(Boolean).join(', ')}
                {' · '}
                <Link to="/trips" className="text-accent underline underline-offset-2">ver todos</Link>
              </>
            }
          />
          <Stat
            id="resumen-chollos" label="Con chollo ahora" value={deals}
            detail={deals ? `${plural(deals, 'viaje cumple', 'viajes cumplen')} sus reglas de aviso` : 'Ninguno cumple ahora sus reglas'}
          />
          <Stat
            id="resumen-mas-barato" label="El más barato ahora" value={cheapest ? fmtPrice(cheapest.best!.total) : '—'}
            detail={cheapest
              ? <><Link to={tripPath(cheapest.id)} className="text-accent underline underline-offset-2">{cheapest.name}</Link> · {comboDates(cheapest)}</>
              : 'Sin precios todavía: pulsa «Comprobar todo»'}
          />
        </div>
      )}
      {soon.length > 0 && (
        <p className="mt-3 flex flex-wrap items-center gap-1.5 text-xs text-muted">
          Próximamente:
          {soon.map((k) => <Badge key={k.key}>{k.label} · {k.since}</Badge>)}
        </p>
      )}

      <Card className="mt-6" aria-labelledby="chollos-ahora">
        <CardHeader
          id="chollos-ahora"
          title={<span className="inline-flex items-center gap-1.5"><Sparkles className="size-4 text-deal" aria-hidden="true" /> Chollos ahora</span>}
          description="La combinación más barata de cada viaje que cumple sus reglas de aviso."
        />
        <CurrentDeals trips={list} />
      </Card>

      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <Card aria-labelledby="ultimos-avisos">
          <CardHeader id="ultimos-avisos" title="Últimos avisos" />
          {alerts.data?.length ? <AlertsTable alerts={alerts.data} /> : (
            <p className="text-sm text-muted">Todavía no se ha enviado ningún aviso.</p>
          )}
        </Card>
        <Card aria-labelledby="ultimas-ejecuciones">
          <CardHeader
            id="ultimas-ejecuciones"
            title="Últimas ejecuciones"
            actions={<Link to="/runs" className="text-sm text-accent hover:underline">Ver todas</Link>}
          />
          {runs.data?.length ? <RunsTable runs={runs.data} /> : <p className="text-sm text-muted">Sin ejecuciones todavía.</p>}
        </Card>
      </div>
    </>
  )
}
