import { ChevronLeft, Pencil, Play } from 'lucide-react'
import { useRef, useState } from 'react'
import { Link, useParams } from 'react-router'
import { useCharts, useDateHistory, useProviders, useStatus, useWatch } from '@/api/queries'
import { Button, buttonClass } from '@/components/ui/button'
import { Badge, Card, CardHeader, PageHeader, TableWrap, tableClass } from '@/components/ui/card'
import { LoadError, PageLoading, Skeleton } from '@/components/ui/feedback'
import { Field, Select } from '@/components/ui/form'
import { CalendarLegend, PriceCalendar } from '@/components/watch/PriceCalendar'
import { PriceChart } from '@/components/watch/PriceChart'
import { ProviderTile } from '@/components/watch/ProviderTile'
import { RoutePill, rulesText } from '@/components/watch/rules'
import { AlertsTable } from '@/components/watch/tables'
import { cn } from '@/lib/cn'
import { fmtDateTime, fmtDay, fmtPrice } from '@/lib/format'
import { useRunNow, useTitle } from '@/lib/hooks'

export function WatchDetailPage() {
  const id = Number(useParams().id)
  const detail = useWatch(id)
  const charts = useCharts(id)
  const provider = useProviders()
  const run = useRunNow()
  const running = useStatus().data?.running
  const [filter, setFilter] = useState('')
  const [picked, setPicked] = useState('')
  const historyRef = useRef<HTMLElement>(null)
  useTitle(detail.data?.watch.name)

  const rows = detail.data?.prices ?? []
  const dates = [...new Set(rows.map((r) => r.flight_date))].sort()
  const date = picked || rows[0]?.flight_date || ''
  const history = useDateHistory(id, date)

  if (detail.isPending) return <PageLoading />
  if (detail.isError) return <LoadError error={detail.error} />
  const { watch: w, stats, checks, alerts, trips } = detail.data
  const shown = filter ? rows.filter((r) => r.provider === filter) : rows

  const selectDay = (d: string) => {
    setPicked(d)
    historyRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  return (
    <>
      <PageHeader
        back={
          <Link to="/" className="inline-flex items-center gap-1 text-sm text-muted hover:text-fg">
            <ChevronLeft className="size-4" aria-hidden="true" /> Panel
          </Link>
        }
        title={
          <span className="flex flex-wrap items-center gap-3">
            {w.name}
            {!w.enabled && <Badge tone="warn">en pausa</Badge>}
          </span>
        }
        description={
          <span className="flex flex-wrap items-center gap-2">
            <RoutePill origin={w.origin} destination={w.destination} />
            {rulesText(w)}
          </span>
        }
        actions={
          <>
            <Button onClick={() => run.mutate(w.id)} disabled={running} loading={run.isPending}>
              {!run.isPending && <Play />} Comprobar ahora
            </Button>
            <Link to={`/watches/${w.id}/edit`} className={buttonClass('secondary')}><Pencil /> Editar</Link>
          </>
        }
      />

      {trips.length > 0 && (
        <p className="-mt-3 mb-4 text-sm text-muted">
          Tramo de {trips.length === 1 ? 'un viaje' : 'los viajes'}:{' '}
          {trips.map((t, i) => (
            <span key={t.id}>
              {i > 0 && ', '}
              <Link to={`/trips/${t.id}`} className="text-fg underline underline-offset-2">{t.name}</Link>
            </span>
          ))}
        </p>
      )}

      <div className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {stats.map((s) => <ProviderTile key={s.key} stat={s} detail className="bg-surface shadow-card" />)}
      </div>

      <Card className="mb-6" aria-labelledby="calendario">
        <CardHeader
          id="calendario"
          title="Precios por fecha de vuelo"
          description="Última comprobación. Pulsa un precio para abrir esa fecha en la web, o el número del día para ver su historial."
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
          <p className="text-sm text-muted">Todavía no hay precios guardados. Pulsa «Comprobar ahora».</p>
        )}
      </Card>

      <div className="mb-6 grid gap-4 lg:grid-cols-2">
        <Card aria-labelledby="evolucion">
          <CardHeader id="evolucion" title="Evolución del precio mínimo" description="El precio más bajo encontrado en cada día de comprobación." />
          {charts.data ? <PriceChart data={charts.data.min_over_time} label="Evolución del precio mínimo por web" /> : <Skeleton className="h-64" />}
        </Card>
        <Card aria-labelledby="por-fecha">
          <CardHeader id="por-fecha" title="Precio actual por fecha de vuelo" description="Qué días salen más baratos en cada web." />
          {charts.data ? <PriceChart data={charts.data.by_flight_date} label="Precio actual por fecha de vuelo" /> : <Skeleton className="h-64" />}
        </Card>
      </div>

      <Card ref={historyRef} className="mb-6 scroll-mt-20" aria-labelledby="historial-fecha">
        <CardHeader
          id="historial-fecha"
          title="Historial de una fecha concreta"
          description="Cómo ha cambiado el precio de un mismo vuelo con el paso de los días."
          actions={
            dates.length > 0 && (
              <Field label={<span className="sr-only">Fecha de vuelo</span>} className="w-56">
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

      <div className="grid gap-4 lg:grid-cols-2">
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
        <Card aria-labelledby="avisos">
          <CardHeader id="avisos" title="Avisos enviados" />
          {alerts.length ? <AlertsTable alerts={alerts} showWatch={false} />
            : <p className="text-sm text-muted">Aún no se ha enviado ningún aviso de esta vigilancia.</p>}
        </Card>
      </div>
    </>
  )
}
