import { ArrowRight } from 'lucide-react'
import type { Watch } from '@/api/types'
import { fmtDay, fmtPrice, stopsRule } from '@/lib/format'

/** «SVQ → TCI» con aspecto de billete. */
export function RoutePill({ origin, destination }: { origin: string; destination: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-lg bg-surface-2 px-2 py-0.5 font-mono text-xs font-semibold tracking-wider">
      {origin}
      <ArrowRight className="size-3 text-muted" aria-label="a" />
      {destination}
    </span>
  )
}

/** Resumen legible de las reglas de aviso de una vigilancia. */
export function rulesText(w: Watch): string {
  const parts = [w.max_price != null ? `avisa si ≤ ${fmtPrice(w.max_price)}` : 'sin precio máximo']
  parts.push(`o −${Math.round(w.discount_pct)} % sobre lo habitual`)
  parts.push(stopsRule(w.max_stops))
  if (w.date_from || w.date_to)
    parts.push(`${w.date_from ? fmtDay(w.date_from) : '…'} – ${w.date_to ? fmtDay(w.date_to) : '…'}`)
  return parts.join(' · ')
}
