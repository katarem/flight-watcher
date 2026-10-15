import { ChevronLeft, Pencil, Play } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { useStatus, useTrip, useTripOptions } from '@/api/queries'
import type { Trip, TripCombo } from '@/api/types'
import { Button, buttonClass } from '@/components/ui/button'
import { Badge, Card, CardHeader, PageHeader, TableWrap, tableClass } from '@/components/ui/card'
import { LoadError, PageLoading, Skeleton } from '@/components/ui/feedback'
import { Field, Select } from '@/components/ui/form'
import { BestCombo, DealBadge, LegLink, TripLegs, TripPill, TripWarnings, hasNights, tripRulesText } from '@/components/trip/parts'
import { PriceChart } from '@/components/watch/PriceChart'
import { AlertsTable } from '@/components/watch/tables'
import { fmtDay, fmtPrice } from '@/lib/format'
import { useRunTrip, useTitle } from '@/lib/hooks'
import { tripPath } from '@/lib/paths'

const TOTAL = { total: { label: 'Total', color: 'var(--fw-accent)' } }
const TOP = 15

function CombosTable({ combos, label, trip, showOut = true }: {
  combos: TripCombo[]; label: string; trip: Trip; showOut?: boolean
}) {
  const nights = hasNights(trip)
  const out = trip.outbound ? 'Ida' : 'Entrada'
  const many = trip.party.size > 1
  const single = [trip.outbound, trip.return, trip.stay].filter(Boolean).length === 1
  return (
    <TableWrap label={label}>
      <table className={tableClass}>
        <thead>
          <tr>
            {showOut && <th scope="col">{out}</th>}
            {nights && <th scope="col">{trip.return ? 'Vuelta' : 'Salida'}</th>}
            {nights && <th scope="col" className="text-right!">Noches</th>}
            {trip.outbound && <th scope="col">Tramo de ida</th>}
            {trip.return && <th scope="col">Tramo de vuelta</th>}
            {trip.stay && <th scope="col">Alojamiento</th>}
            <th scope="col" className="text-right!">{single ? 'Precio' : 'Total'}</th>
          </tr>
        </thead>
        <tbody>
          {combos.map((c) => (
            <tr key={`${c.out_date}-${c.nights ?? 'ow'}`}>
              {showOut && <td className="whitespace-nowrap">{fmtDay(c.out_date)}</td>}
              {nights && <td className="whitespace-nowrap">{c.ret_date ? fmtDay(c.ret_date) : '—'}</td>}
              {nights && <td className="text-right tabular-nums">{c.nights}</td>}
              {trip.outbound && <td>{c.out ? <LegLink leg={c.out} /> : '—'}</td>}
              {trip.return && <td>{c.ret ? <LegLink leg={c.ret} /> : '—'}</td>}
              {trip.stay && <td>{c.stay ? <LegLink leg={c.stay} /> : '—'}</td>}
              <td className="text-right whitespace-nowrap">
                <span className="font-semibold tabular-nums">{fmtPrice(c.total)}</span>
                {c.deal && <span className="ml-1.5"><DealBadge /></span>}
                {many && <span className="block text-xs text-muted tabular-nums">{fmtPrice(c.per_person)}/persona</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </TableWrap>
  )
}

export function TripDetailPage() {
  const id = Number(useParams().id)
  const detail = useTrip(id)
  const run = useRunTrip()
  const running = useStatus().data?.running
  const [picked, setPicked] = useState('')
  useTitle(detail.data?.trip.name)

  const quotes = detail.data?.quotes ?? []
  const cheapest = [...quotes].sort((a, b) => a.total - b.total || a.out_date.localeCompare(b.out_date))
  const date = picked || cheapest[0]?.out_date || ''
  const options = useTripOptions(id, date)

  if (detail.isPending) return <PageLoading />
  if (detail.isError) return <LoadError error={detail.error} />
  const { trip: t, base, trend, alerts } = detail.data
  const nights = hasNights(t)
  const day = t.outbound ? 'ida' : 'entrada'

  const byDate = { labels: quotes.map((q) => q.out_date), series: { total: quotes.map((q) => q.total) } }
  const evolution = { labels: trend.map((x) => x.d), series: { total: trend.map((x) => x.p) } }

  return (
    <>
      <PageHeader
        back={
          <Link to="/trips" className="inline-flex items-center gap-1 text-sm text-muted hover:text-fg">
            <ChevronLeft className="size-4" aria-hidden="true" /> Viajes
          </Link>
        }
        title={
          <span className="flex flex-wrap items-center gap-3">
            {t.name}
            {!t.enabled && <Badge tone="warn">en pausa</Badge>}
          </span>
        }
        description={
          <span className="flex flex-wrap items-center gap-2">
            <TripPill trip={t} />
            {tripRulesText(t)}
          </span>
        }
        actions={
          <>
            <Button onClick={() => run.mutate(t.id)} disabled={running} loading={run.isPending}>
              {!run.isPending && <Play />} Comprobar ahora
            </Button>
            <Link to={tripPath(t.id, '/edit')} className={buttonClass('secondary')}><Pencil /> Editar</Link>
          </>
        }
      />

      <div className="mb-6 space-y-3">
        <TripLegs trip={t} />
        <TripWarnings warnings={t.warnings} />
        <BestCombo combo={cheapest[0] ?? null} base={base} nDates={quotes.length} trip={t} className="bg-surface shadow-card sm:max-w-md" />
      </div>

      <Card className="mb-6" aria-labelledby="combinaciones">
        <CardHeader
          id="combinaciones"
          title={nights ? 'Combinaciones más baratas' : 'Fechas más baratas'}
          description={nights
            ? `La mejor de cada fecha de ${day} (las ${TOP} más baratas), con los precios actuales de cada tramo.`
            : `La más barata de cada fecha de ida (las ${TOP} más baratas), con los precios actuales.`}
        />
        {cheapest.length ? <CombosTable combos={cheapest.slice(0, TOP)} label="Combinaciones más baratas" trip={t} />
          : <p className="text-sm text-muted">Todavía no hay combinaciones. Pulsa «Comprobar ahora».</p>}
      </Card>

      {nights && (
        <Card className="mb-6" aria-labelledby="por-noches">
          <CardHeader
            id="por-noches"
            title={`Todas las noches de una fecha de ${day}`}
            description={`Cuánto sale el viaje según el día de ${t.return ? 'vuelta' : 'salida'}.`}
            actions={
              quotes.length > 0 && (
                <Field label={<span className="sr-only">Fecha de {day}</span>} className="w-full sm:w-72">
                  {(fid) => (
                    <Select id={fid} value={date} onChange={(e) => setPicked(e.target.value)}>
                      {quotes.map((q) => <option key={q.out_date} value={q.out_date}>{fmtDay(q.out_date)} · desde {fmtPrice(q.total)}</option>)}
                    </Select>
                  )}
                </Field>
              )
            }
          />
          {!quotes.length ? <p className="text-sm text-muted">Aún no hay datos.</p>
            : options.data ? <CombosTable combos={options.data} label={`Noches con ${day} el ${fmtDay(date)}`} trip={t} showOut={false} />
              : <Skeleton className="h-32" />}
        </Card>
      )}

      <div className="mb-6 grid gap-4 lg:grid-cols-2">
        <Card aria-labelledby="total-por-fecha">
          <CardHeader id="total-por-fecha" title={`Total por fecha de ${day}`} description={`La combinación más barata de cada día de ${day}.`} />
          <PriceChart data={byDate} names={TOTAL} label={`Total del viaje por fecha de ${day}`} />
        </Card>
        <Card aria-labelledby="evolucion">
          <CardHeader id="evolucion" title="Evolución del mejor total" description="El viaje más barato encontrado en cada día de comprobación." />
          <PriceChart data={evolution} names={TOTAL} label="Evolución del mejor total del viaje" />
        </Card>
      </div>

      <Card aria-labelledby="avisos">
        <CardHeader id="avisos" title="Avisos enviados" />
        {alerts.length ? <AlertsTable alerts={alerts} showTrip={false} />
          : <p className="text-sm text-muted">Aún no se ha enviado ningún aviso de este viaje.</p>}
      </Card>
    </>
  )
}
