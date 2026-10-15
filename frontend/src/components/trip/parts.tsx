import { ArrowLeftRight, ArrowRight, ArrowUpRight, Hotel, Sparkles } from 'lucide-react'
import { Link } from 'react-router'
import { useProviders } from '@/api/queries'
import type { Trip, TripCombo, TripPrice } from '@/api/types'
import { Badge } from '@/components/ui/card'
import { cn } from '@/lib/cn'
import { fmtDay, fmtNights, fmtNightsRange, fmtPrice, priceExtras } from '@/lib/format'
import { legPath } from '@/lib/paths'
import { useOfferText } from '@/lib/stays'

/** «SVQ ⇄ TCI» (ida y vuelta), «SVQ → TCI» (solo ida) y, con alojamiento, su destino; con aspecto de billete. */
export function TripPill({ trip }: { trip: Trip }) {
  const Arrow = trip.return ? ArrowLeftRight : ArrowRight
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      {trip.outbound && (
        <span className="inline-flex items-center gap-1.5 rounded-lg bg-surface-2 px-2 py-0.5 font-mono text-xs font-semibold tracking-wider">
          {trip.outbound.origin}
          <Arrow className="size-3 text-muted" aria-label={trip.return ? 'ida y vuelta' : 'solo ida'} />
          {trip.outbound.destination}
        </span>
      )}
      {trip.stay && (
        <span className="inline-flex items-center gap-1.5 rounded-lg bg-surface-2 px-2 py-0.5 text-xs font-semibold">
          <Hotel className="size-3 text-muted" aria-label="alojamiento en" />
          {trip.stay.destination}
        </span>
      )}
    </span>
  )
}

/** ¿Tiene el viaje noches? (con vuelta o con alojamiento). */
export const hasNights = (t: Trip) => !!(t.return || t.stay)

/** Resumen legible de las noches, los viajeros, las reglas de aviso y la ventana de fechas de un viaje. */
export function tripRulesText(t: Trip): string {
  const parts = [hasNights(t) ? fmtNightsRange(t.min_nights, t.max_nights) : 'solo ida']
  if (t.party.size > 1 || t.party.label.includes('·')) parts.push(t.party.label)
  const what = hasNights(t) || !t.outbound ? 'el total' : 'el precio'
  if (t.max_total != null) parts.push(`avisa si ${what} ≤ ${fmtPrice(t.max_total)}`)
  if (t.max_per_person != null) parts.push(`${t.max_total != null ? 'o' : 'avisa si'} ≤ ${fmtPrice(t.max_per_person)}/persona`)
  if (t.max_total == null && t.max_per_person == null) parts.push('sin precio máximo')
  parts.push(`o −${Math.round(t.discount_pct)} % sobre lo habitual`)
  const from = t.outbound ? 'ida' : 'entrada'
  if (t.date_from || t.date_to)
    parts.push(`${from} ${t.date_from ? fmtDay(t.date_from) : '…'} – ${t.date_to ? fmtDay(t.date_to) : '…'}`)
  return parts.join(' · ')
}

/** «Ida: Sevilla → Tenerife · Vuelta: Tenerife → Sevilla · Alojamiento: Puerto de la Cruz», con enlaces al detalle de
 *  cada tramo. */
export function TripLegs({ trip, className }: { trip: Trip; className?: string }) {
  const legs = [
    trip.outbound && { label: 'Ida', id: trip.outbound.id, name: trip.outbound.name },
    trip.return && { label: 'Vuelta', id: trip.return.id, name: trip.return.name },
    trip.stay && { label: 'Alojamiento', id: trip.stay.id, name: trip.stay.name },
  ].filter((l): l is { label: string; id: number; name: string } => !!l)
  return (
    <p className={cn('text-sm text-muted', className)}>
      {legs.map((l, i) => (
        <span key={l.id}>
          {i > 0 && ' · '}
          {l.label}: <Link to={legPath(trip.id, l.id)} className="text-fg underline underline-offset-2">{l.name}</Link>
        </span>
      ))}
    </p>
  )
}

/** Precio de un tramo con su web, enlazado a esa fecha en la web (en una estancia, también el alojamiento). */
export function LegLink({ leg }: { leg: TripPrice }) {
  const provider = useProviders()
  const offerText = useOfferText()
  const extras = [leg.route, leg.offer ? offerText(leg.offer) : '', priceExtras(leg)].filter(Boolean).join(' · ')
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

/** Fechas de una combinación: «12/11 → 19/11 · 7 noches» o, sin noches (solo ida), «12/11». */
export const comboDates = (c: TripCombo) =>
  c.ret_date ? `${fmtDay(c.out_date)} → ${fmtDay(c.ret_date)} · ${fmtNights(c.nights ?? 0)}` : fmtDay(c.out_date)

/** Los tramos de una combinación con su etiqueta (sin etiqueta si solo hay uno). */
export function ComboParts({ combo }: { combo: TripCombo }) {
  const parts = [
    combo.out && { label: 'Ida', leg: combo.out },
    combo.ret && { label: 'Vuelta', leg: combo.ret },
    combo.stay && { label: 'Alojamiento', leg: combo.stay },
  ].filter((p): p is { label: string; leg: TripPrice } => !!p)
  return (
    <ul className="space-y-1 text-sm">
      {parts.map((p) => (
        <li key={p.label}>{parts.length > 1 && `${p.label}: `}<LegLink leg={p.leg} /></li>
      ))}
    </ul>
  )
}

/** La combinación más barata ahora mismo: total, fechas y un enlace por tramo. */
export function BestCombo({ combo, base, nDates, trip, className }: {
  combo: TripCombo | null
  base: number | null
  nDates?: number
  trip: Trip
  className?: string
}) {
  const many = trip.party.size > 1
  return (
    <div className={cn('rounded-xl border border-line bg-surface-2/50 p-3.5', className)}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium">{trip.outbound ? 'Viaje más barato ahora' : 'Estancia más barata ahora'}</span>
        {combo?.deal && <DealBadge />}
      </div>
      {combo ? (
        <>
          <p className="mt-1 text-3xl font-semibold tracking-tight tabular-nums">
            {fmtPrice(combo.total)}
            {many && <span className="ml-2 text-sm font-normal text-muted">{fmtPrice(combo.per_person)}/persona</span>}
          </p>
          <p className="text-sm text-muted">{comboDates(combo)}</p>
          <ComboParts combo={combo} />
          {(base != null || nDates != null) && (
            <p className="mt-2 text-xs text-muted">
              {[base != null && `habitual ≈ ${fmtPrice(base)}`,
                nDates != null && `${nDates} ${nDates === 1 ? 'fecha' : 'fechas'} de ${trip.outbound ? 'ida' : 'entrada'} con precio`]
                .filter(Boolean).join(' · ')}
            </p>
          )}
        </>
      ) : (
        <p className="mt-2 text-sm text-muted">
          {!hasNights(trip) ? 'Sin precios todavía: pulsa «Comprobar» para traer los de la ida.'
            : !trip.outbound ? 'Sin precios todavía: pulsa «Comprobar» para buscar alojamiento en las fechas elegidas.'
              : `Sin combinaciones todavía: hacen falta precios recientes de ${trip.return && trip.stay
                ? 'la ida, la vuelta y el alojamiento' : trip.return ? 'la ida y de la vuelta' : 'la ida y del alojamiento'} con las noches elegidas.`}
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
