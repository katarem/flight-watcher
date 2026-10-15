import { ArrowUpRight, ChevronLeft, Hotel, Pencil } from 'lucide-react'
import { useRef, useState } from 'react'
import { Link, Navigate, useParams } from 'react-router'
import { useCharts, useDateHistory, useMeta, useProviders, useWatch } from '@/api/queries'
import { buttonClass } from '@/components/ui/button'
import { Badge, Card, CardHeader, PageHeader, TableWrap, tableClass } from '@/components/ui/card'
import { LoadError, PageLoading, Skeleton } from '@/components/ui/feedback'
import { Field, Select } from '@/components/ui/form'
import { CalendarLegend, PriceCalendar } from '@/components/watch/PriceCalendar'
import { PriceChart } from '@/components/watch/PriceChart'
import { ProviderTile } from '@/components/watch/ProviderTile'
import { RoutePill } from '@/components/watch/rules'
import { cn } from '@/lib/cn'
import type { PriceRow, StayFilters } from '@/api/types'
import { fmtDateTime, fmtDay, fmtPrice, stopsRule } from '@/lib/format'
import { useTitle } from '@/lib/hooks'
import { useKind } from '@/lib/kinds'
import { legPath, tripPath } from '@/lib/paths'
import { useOfferText } from '@/lib/stays'

const ROLES = { outbound: 'Ida', return: 'Vuelta', stay: 'Alojamiento' } as const
const TOP_STAYS = 20

/** «1 habitación · hotel o apartamento · nota 8+»: los filtros de una estancia (como `StayFilters.describe`). */
function useFiltersText() {
  const options = useMeta().data?.stay_options
  const names = (keys: string[], list = options?.types) =>
    keys.map((k) => list?.find((o) => o.key === k)?.label.toLowerCase() ?? k).join(' o ')
  return (f: StayFilters) => [
    f.rooms === 1 ? '1 habitación' : `${f.rooms} habitaciones`,
    f.types.length > 0 && names(f.types),
    f.entire && 'alojamiento entero',
    f.min_stars && `${f.min_stars}★ o más`,
    f.min_rating != null && `nota ${f.min_rating}+`,
    f.boards.length > 0 && names(f.boards, options?.boards),
    f.free_cancel && 'cancelación gratuita',
    f.amenities.length > 0 && f.amenities.map((k) => options?.amenities.find((o) => o.key === k)?.label.toLowerCase() ?? k).join(', '),
  ].filter(Boolean).join(' · ')
}

/** Las estancias más baratas ahora (entrada × noches) con su alojamiento y su enlace. */
function StaysTable({ rows }: { rows: PriceRow[] }) {
  const provider = useProviders()
  const offerText = useOfferText()
  return (
    <TableWrap label="Estancias más baratas">
      <table className={tableClass}>
        <thead>
          <tr>
            <th scope="col">Entrada</th>
            <th scope="col" className="text-right!">Noches</th>
            <th scope="col">Web</th>
            <th scope="col">Alojamiento</th>
            <th scope="col" className="text-right!">Precio</th>
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, TOP_STAYS).map((r) => (
            <tr key={`${r.provider}-${r.flight_date}-${r.nights}`}>
              <td className="whitespace-nowrap">{fmtDay(r.flight_date)}</td>
              <td className="text-right tabular-nums">{r.nights}</td>
              <td>{provider(r.provider).label}</td>
              <td>
                <a href={r.link} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-0.5 text-accent underline underline-offset-2">
                  {offerText(r.offer)}
                  <ArrowUpRight className="size-3.5 shrink-0" aria-hidden="true" />
                  <span className="sr-only">(se abre en otra pestaña)</span>
                </a>
              </td>
              <td className="text-right font-semibold whitespace-nowrap tabular-nums">{fmtPrice(r.price)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </TableWrap>
  )
}

/** Detalle de solo lectura de un tramo de un viaje (calendario, gráficas e histórico). Se edita desde el viaje. */
export function LegDetailPage() {
  const params = useParams()
  const id = Number(params.legId)
  const detail = useWatch(id)
  const charts = useCharts(id)
  const provider = useProviders()
  const [filter, setFilter] = useState('')
  const [picked, setPicked] = useState('')
  const historyRef = useRef<HTMLElement>(null)
  const kind = useKind(detail.data?.watch.kind ?? 'flight')
  const filtersText = useFiltersText()
  useTitle(detail.data?.watch.name)

  const rows = detail.data?.prices ?? []
  const dates = [...new Set(rows.map((r) => r.flight_date))].sort()
  const date = picked || rows[0]?.flight_date || ''
  const history = useDateHistory(id, date)

  if (detail.isPending) return <PageLoading />
  if (detail.isError) return <LoadError error={detail.error} />
  const { watch: w, role, stats, checks, trip } = detail.data
  // Un enlace con otro viaje en la URL lleva a la del suyo.
  if (String(trip.id) !== params.id) return <Navigate to={legPath(trip.id, w.id)} replace />
  const shown = filter ? rows.filter((r) => r.provider === filter) : rows
  const stay = role === 'stay'
  // En una estancia, la fecha es la de entrada (y cada día tiene varias noches: el calendario da la más barata).
  const what = stay ? 'entrada' : kind.noun

  const selectDay = (d: string) => {
    setPicked(d)
    historyRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  return (
    <>
      <PageHeader
        back={
          <Link to={tripPath(trip.id)} className="inline-flex items-center gap-1 text-sm text-muted hover:text-fg">
            <ChevronLeft className="size-4" aria-hidden="true" /> {trip.name}
          </Link>
        }
        title={
          <span className="flex flex-wrap items-center gap-3">
            {w.name}
            <Badge>{ROLES[role]}</Badge>
            {!w.enabled && <Badge tone="warn">en pausa</Badge>}
          </span>
        }
        description={
          stay ? (
            <span className="flex flex-wrap items-center gap-2">
              <span className="inline-flex items-center gap-1.5 rounded-lg bg-surface-2 px-2 py-0.5 text-xs font-semibold">
                <Hotel className="size-3 text-muted" aria-hidden="true" /> {w.destination}
              </span>
              Alojamiento del viaje «{trip.name}» ({w.filters ? filtersText(w.filters) : 'sin filtros'}). Se edita desde el viaje.
            </span>
          ) : (
            <span className="flex flex-wrap items-center gap-2">
              <RoutePill origin={w.origin} destination={w.destination} />
              Tramo de {ROLES[role].toLowerCase()} del viaje «{trip.name}» ({stopsRule(w.max_stops)}). Se edita desde el viaje.
            </span>
          )
        }
        actions={<Link to={tripPath(trip.id, '/edit')} className={buttonClass('secondary')}><Pencil /> Editar el viaje</Link>}
      />

      <div className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {stats.map((s) => <ProviderTile key={s.key} stat={s} detail className="bg-surface shadow-card" plural={kind.plural} />)}
      </div>

      <Card className="mb-6" aria-labelledby="calendario">
        <CardHeader
          id="calendario"
          title={`Precios por fecha de ${what}`}
          description={stay
            ? 'La estancia más barata de cada fecha de entrada (con cualquiera de las noches del viaje), de los últimos días. Pulsa un precio para abrirla, o el número del día para ver su historial.'
            : 'Última comprobación. Pulsa un precio para abrir esa fecha en la web, o el número del día para ver su historial.'}
          actions={
            stats.length > 1 && (
              <div role="group" aria-label="Filtrar por web" className="flex flex-wrap gap-1 rounded-xl bg-surface-2 p-1">
                {[{ key: '', label: 'Todas' }, ...stats].map((s) => (
                  <button
                    key={s.key}
                    type="button"
                    aria-pressed={filter === s.key}
                    onClick={() => setFilter(s.key)}
                    className={cn('rounded-lg px-3 py-1 text-sm font-medium transition',
                      filter === s.key ? 'bg-surface text-fg shadow-sm' : 'text-muted hover:text-fg')}
                  >
                    {s.label}
                  </button>
                ))}
              </div>
            )
          }
        />
        {shown.length ? (
          <div className="space-y-4">
            <CalendarLegend providers={stats.filter((s) => !filter || s.key === filter)} />
            <PriceCalendar rows={shown} selected={date} onSelectDay={selectDay} />
          </div>
        ) : (
          <p className="text-sm text-muted">Todavía no hay precios guardados. Pulsa «Comprobar ahora» en el viaje.</p>
        )}
      </Card>

      {stay && rows.length > 0 && (
        <Card className="mb-6" aria-labelledby="estancias">
          <CardHeader id="estancias" title="Estancias más baratas"
            description={`Las ${TOP_STAYS} más baratas por fecha de entrada y noches, con el alojamiento que cumple los filtros.`} />
          <StaysTable rows={shown} />
        </Card>
      )}

      <div className="mb-6 grid gap-4 lg:grid-cols-2">
        <Card aria-labelledby="evolucion">
          <CardHeader id="evolucion" title="Evolución del precio mínimo" description="El precio más bajo encontrado en cada día de comprobación." />
          {charts.data ? <PriceChart data={charts.data.min_over_time} label="Evolución del precio mínimo por web" /> : <Skeleton className="h-64" />}
        </Card>
        <Card aria-labelledby="por-fecha">
          <CardHeader id="por-fecha" title={`Precio actual por fecha de ${what}`} description="Qué días salen más baratos en cada web." />
          {charts.data ? <PriceChart data={charts.data.by_flight_date} label={`Precio actual por fecha de ${what}`} /> : <Skeleton className="h-64" />}
        </Card>
      </div>

      <Card ref={historyRef} className="mb-6 scroll-mt-20" aria-labelledby="historial-fecha">
        <CardHeader
          id="historial-fecha"
          title="Historial de una fecha concreta"
          description={stay ? 'Cómo ha cambiado la estancia más barata de una misma fecha de entrada con el paso de los días.'
            : `Cómo ha cambiado el precio de un mismo ${kind.noun} con el paso de los días.`}
          actions={
            dates.length > 0 && (
              <Field label={<span className="sr-only">Fecha de {what}</span>} className="w-56">
                {(fid) => (
                  <Select id={fid} value={date} onChange={(e) => setPicked(e.target.value)}>
                    {dates.map((d) => <option key={d} value={d}>{fmtDay(d)}</option>)}
                  </Select>
                )}
              </Field>
            )
          }
        />
        {!dates.length ? <p className="text-sm text-muted">Aún no hay datos.</p>
          : history.data ? <PriceChart data={history.data} label={`Historial del precio para el ${fmtDay(date)}`} />
            : <Skeleton className="h-64" />}
      </Card>

      <Card aria-labelledby="comprobaciones">
        <CardHeader id="comprobaciones" title="Historial de comprobaciones" />
        {checks.length ? (
          <TableWrap label="Historial de comprobaciones">
            <table className={tableClass}>
              <thead>
                <tr>
                  <th scope="col">Cuándo</th>
                  <th scope="col">Web</th>
                  <th scope="col" className="text-right!">Fechas</th>
                  <th scope="col" className="text-right!">Mínimo</th>
                  <th scope="col" className="text-right!">Media</th>
                </tr>
              </thead>
              <tbody>
                {checks.map((c) => (
                  <tr key={`${c.provider}-${c.checked_at}`}>
                    <td className="whitespace-nowrap text-muted">{fmtDateTime(c.checked_at)}</td>
                    <td>{provider(c.provider).label}</td>
                    <td className="text-right tabular-nums">{c.n}</td>
                    <td className="text-right font-semibold tabular-nums">{fmtPrice(c.mn)}</td>
                    <td className="text-right tabular-nums">{fmtPrice(c.av)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        ) : <p className="text-sm text-muted">Sin comprobaciones todavía.</p>}
      </Card>
    </>
  )
}
