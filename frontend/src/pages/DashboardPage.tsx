import { ArrowUpRight, Luggage, Plus, Sparkles } from 'lucide-react'
import { Link } from 'react-router'
import { useAlerts, useMeta, useRuns, useTrips, useWatches } from '@/api/queries'
import type { KindMeta, TripCard, WatchCard } from '@/api/types'
import { buttonClass } from '@/components/ui/button'
import { Badge, Card, CardHeader, PageHeader, TableWrap, tableClass } from '@/components/ui/card'
import { LoadError, PageLoading } from '@/components/ui/feedback'
import { AlertsTable, RunsTable } from '@/components/watch/tables'
import { fmtDay, fmtPrice, priceExtras } from '@/lib/format'
import { useTitle } from '@/lib/hooks'
import { KIND_ICONS, watchPath } from '@/lib/kinds'

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`

/** Resumen de un apartado (un transporte o los viajes): cuántas vigilancias, chollos y el mejor precio. */
function SectionCard({ icon, title, to, newTo, newLabel, lines, best, id }: {
  icon: React.ReactNode
  title: string
  to: string
  newTo: string
  newLabel: string
  lines: string[]
  best: number | null
  id: string
}) {
  return (
    <Card aria-labelledby={id} className="flex flex-col gap-3">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <span className="grid size-9 place-items-center rounded-xl bg-accent-soft text-accent [&_svg]:size-4.5" aria-hidden="true">
            {icon}
          </span>
          <h2 id={id} className="text-lg font-semibold tracking-tight">
            <Link to={to} className="hover:underline">{title}</Link>
          </h2>
        </div>
        {best != null && (
          <div className="text-right">
            <p className="text-xs text-muted">desde</p>
            <p className="text-lg font-semibold tabular-nums">{fmtPrice(best)}</p>
          </div>
        )}
      </div>
      <ul className="space-y-0.5 text-sm text-muted">
        {lines.map((l) => <li key={l}>{l}</li>)}
      </ul>
      <div className="mt-auto flex flex-wrap gap-2">
        <Link to={to} className={buttonClass('secondary', 'sm')}>Ver {title.toLowerCase()}</Link>
        <Link to={newTo} className={buttonClass('ghost', 'sm')}><Plus /> {newLabel}</Link>
      </div>
    </Card>
  )
}

function transportCard(k: KindMeta, watches: WatchCard[]) {
  const mine = watches.filter((w) => w.kind === k.key)
  const prices = mine.flatMap((w) => w.stats.map((s) => s.best?.price)).filter((p): p is number => p != null)
  const deals = mine.reduce((n, w) => n + w.stats.filter((s) => s.best?.deal && s.active).length, 0)
  const Icon = KIND_ICONS[k.key]
  return (
    <SectionCard
      key={k.key} id={`seccion-${k.key}`} icon={<Icon />} title={k.label} to={k.section} newTo={`${k.section}/new`}
      newLabel={`Vigilar ${k.plural}`}
      best={prices.length ? Math.min(...prices) : null}
      lines={mine.length ? [
        `${plural(mine.length, 'vigilancia', 'vigilancias')} (${mine.filter((w) => w.enabled).length} activas)`,
        deals ? `${plural(deals, 'web con chollo', 'webs con chollo')} ahora mismo` : 'Ningún chollo ahora mismo',
      ] : [`Aún no vigilas ningún ${k.noun}.`]}
    />
  )
}

function tripsCard(trips: TripCard[]) {
  const totals = trips.map((t) => t.best?.total).filter((p): p is number => p != null)
  const deals = trips.filter((t) => t.best?.deal).length
  return (
    <SectionCard
      id="seccion-viajes" icon={<Luggage />} title="Viajes" to="/trips" newTo="/trips/new" newLabel="Nuevo viaje"
      best={totals.length ? Math.min(...totals) : null}
      lines={trips.length ? [
        `${plural(trips.length, 'viaje', 'viajes')} de ida y vuelta`,
        deals ? `${plural(deals, 'con chollo', 'con chollo')} ahora mismo` : 'Ningún chollo ahora mismo',
      ] : ['Junta una ida y una vuelta para que te avise por el precio total.']}
    />
  )
}

/** Los chollos de ahora mismo: el mejor precio de cada web que cumple las reglas de su vigilancia. */
function CurrentDeals({ watches }: { watches: WatchCard[] }) {
  const rows = watches
    .flatMap((w) => w.stats.filter((s) => s.best?.deal && s.active).map((s) => ({ w, s, best: s.best! })))
    .sort((a, b) => a.best.price - b.best.price)
    .slice(0, 8)
  if (!rows.length) return <p className="text-sm text-muted">Ninguna de tus vigilancias tiene ahora un precio de chollo.</p>
  return (
    <TableWrap label="Chollos ahora">
      <table className={tableClass}>
        <thead>
          <tr>
            <th scope="col">Vigilancia</th>
            <th scope="col">Web</th>
            <th scope="col">Fecha</th>
            <th scope="col" className="text-right!">Precio</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ w, s, best }) => (
            <tr key={`${w.id}-${s.key}`}>
              <td><Link to={watchPath(w.kind, w.id)} className="hover:underline">{w.name}</Link></td>
              <td>{s.label}</td>
              <td className="whitespace-nowrap">
                <a href={best.link} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-0.5 text-accent hover:underline">
                  {fmtDay(best.flight_date)} <ArrowUpRight className="size-3.5" aria-hidden="true" />
                  <span className="sr-only">(se abre en otra pestaña)</span>
                </a>
                {priceExtras(best) && <span className="ml-1 text-xs text-muted">{priceExtras(best)}</span>}
              </td>
              <td className="text-right font-semibold whitespace-nowrap tabular-nums">{fmtPrice(best.price)}</td>
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
  const watches = useWatches()
  const trips = useTrips()
  const alerts = useAlerts(8)
  const runs = useRuns(8)

  if (watches.isPending || trips.isPending) return <PageLoading />
  if (watches.isError) return <LoadError error={watches.error} />
  if (trips.isError) return <LoadError error={trips.error} />
  const kinds = meta?.kinds ?? []
  const ready = kinds.filter((k) => k.transport && k.available && k.section)
  const soon = kinds.filter((k) => !k.available && k.since).sort((a, b) => a.since.localeCompare(b.since))

  return (
    <>
      <PageHeader
        title="Panel"
        description="Resumen de tus vigilancias y viajes: entra en cada apartado para ver el detalle."
      />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {ready.map((k) => transportCard(k, watches.data))}
        {tripsCard(trips.data)}
      </div>
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
          description="El precio más bajo de cada web que cumple las reglas de su vigilancia."
        />
        <CurrentDeals watches={watches.data} />
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
