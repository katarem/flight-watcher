import { ArrowLeftRight, ArrowRight, ArrowUpRight, Sparkles } from 'lucide-react'
import { Link } from 'react-router'
import { useProviders } from '@/api/queries'
import type { Trip, TripCombo, TripPrice } from '@/api/types'
import { Badge } from '@/components/ui/card'
import { cn } from '@/lib/cn'
import { fmtDay, fmtNights, fmtNightsRange, fmtPrice, priceExtras } from '@/lib/format'
import { watchPath } from '@/lib/kinds'

/** «SVQ ⇄ TCI» (ida y vuelta) o «SVQ → TCI» (solo ida), con aspecto de billete. */
export function TripPill({ trip }: { trip: Trip }) {
  const Arrow = trip.return ? ArrowLeftRight : ArrowRight
  return (
    <span className="inline-flex items-center gap-1.5 rounded-lg bg-surface-2 px-2 py-0.5 font-mono text-xs font-semibold tracking-wider">
      {trip.outbound.origin}
      <Arrow className="size-3 text-muted" aria-label={trip.return ? 'ida y vuelta' : 'solo ida'} />
      {trip.outbound.destination}
    </span>
  )
}

/** Resumen legible de las noches (si hay vuelta), las reglas de aviso y la ventana de fechas de un viaje. */
export function tripRulesText(t: Trip): string {
  const parts = t.return ? [fmtNightsRange(t.min_nights, t.max_nights)] : ['solo ida']
  parts.push(t.max_total != null ? `avisa si ${t.return ? 'el total' : 'el precio'} ≤ ${fmtPrice(t.max_total)}` : 'sin precio máximo')
  parts.push(`o −${Math.round(t.discount_pct)} % sobre lo habitual`)
  if (t.date_from || t.date_to)
    parts.push(`ida ${t.date_from ? fmtDay(t.date_from) : '…'} – ${t.date_to ? fmtDay(t.date_to) : '…'}`)
  return parts.join(' · ')
}

/** «Ida: Sevilla → Tenerife · Vuelta: Tenerife → Sevilla», con enlaces a cada tramo (solo ida = sin vuelta). */
export function TripLegs({ trip, className }: { trip: Trip; className?: string }) {
  return (
    <p className={cn('text-sm text-muted', className)}>
      Ida: <Link to={watchPath(trip.outbound.kind, trip.outbound.id)} className="text-fg underline underline-offset-2">{trip.outbound.name}</Link>
      {trip.return && (
        <>
          {' · '}
          Vuelta: <Link to={watchPath(trip.return.kind, trip.return.id)} className="text-fg underline underline-offset-2">{trip.return.name}</Link>
        </>
      )}
    </p>
  )
}

/** Precio de un tramo con su web, enlazado a esa fecha en la web. */
export function LegLink({ leg }: { leg: TripPrice }) {
  const provider = useProviders()
  const extras = [leg.route, priceExtras(leg)].filter(Boolean).join(' · ')
  return (
    <>
      <a href={leg.link} target="_blank" rel="noopener noreferrer"
        className="inline-flex items-center gap-0.5 font-medium whitespace-nowrap text-accent underline underline-offset-2">
        {provider(leg.provider).label} {fmtPrice(leg.price)}
        <ArrowUpRight className="size-3.5" aria-hidden="true" />
        <span className="sr-only">(se abre en otra pestaña)</span>
      </a>
      {extras && <span className="ml-1 text-xs text-muted">{extras}</span>}
    </>
  )
}

export const DealBadge = () => (
  <Badge tone="deal"><Sparkles aria-hidden="true" /> chollo</Badge>
)

/** La combinación más barata ahora mismo: total, fechas y un enlace por tramo. */
export function BestCombo({ combo, base, nDates, className }: {
  combo: TripCombo | null
  base: number | null
  nDates?: number
  className?: string
}) {
  return (
    <div className={cn('rounded-xl border border-line bg-surface-2/50 p-3.5', className)}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium">Viaje más barato ahora</span>
        {combo?.deal && <DealBadge />}
      </div>
      {combo ? (
        <>
          <p className="mt-1 text-3xl font-semibold tracking-tight tabular-nums">{fmtPrice(combo.total)}</p>
          <p className="text-sm text-muted">
            {combo.ret_date
              ? `${fmtDay(combo.out_date)} → ${fmtDay(combo.ret_date)} · ${fmtNights(combo.nights ?? 0)}`
              : fmtDay(combo.out_date)}
          </p>
          <ul className="mt-2 space-y-1 text-sm">
            <li>{combo.ret ? 'Ida: ' : ''}<LegLink leg={combo.out} /></li>
            {combo.ret && <li>Vuelta: <LegLink leg={combo.ret} /></li>}
          </ul>
          {(base != null || nDates != null) && (
            <p className="mt-2 text-xs text-muted">
              {[base != null && `habitual ≈ ${fmtPrice(base)}`, nDates != null && `${nDates} ${nDates === 1 ? 'fecha' : 'fechas'} de ida con precio`]
                .filter(Boolean).join(' · ')}
            </p>
          )}
        </>
      ) : (
        <p className="mt-2 text-sm text-muted">
          Sin combinaciones todavía: hacen falta precios recientes de la ida y de la vuelta con las noches elegidas.
        </p>
      )}
    </div>
  )
}

/** Avisos que no impiden guardar el viaje (tramos en pausa o que no encajan). */
export function TripWarnings({ warnings }: { warnings: string[] }) {
  if (!warnings.length) return null
  return (
    <ul className="space-y-1 rounded-xl border border-warn/30 bg-warn/10 p-3 text-sm text-warn">
      {warnings.map((w) => <li key={w}>{w}</li>)}
    </ul>
  )
}
