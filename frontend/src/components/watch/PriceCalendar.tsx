import { motion } from 'motion/react'
import { useMemo } from 'react'
import { useProviders } from '@/api/queries'
import type { PriceRow } from '@/api/types'
import { buildCalendar } from '@/lib/calendar'
import { cn } from '@/lib/cn'
import { fmtDay, fmtPrice, fmtPriceShort, priceExtras } from '@/lib/format'

const WEEKDAYS: [string, string][] = [
  ['L', 'lunes'], ['M', 'martes'], ['X', 'miércoles'], ['J', 'jueves'], ['V', 'viernes'], ['S', 'sábado'], ['D', 'domingo'],
]

/** Precios de la última comprobación por día: pulsar un precio abre esa fecha en la web y pulsar el día
 *  muestra su historial (`onSelectDay`). El color va del más barato (verde) al más caro (rojo). */
export function PriceCalendar({ rows, selected, onSelectDay }: {
  rows: PriceRow[]
  selected: string
  onSelectDay: (date: string) => void
}) {
  const provider = useProviders()
  const months = useMemo(() => buildCalendar(rows), [rows])

  return (
    <div className="grid gap-x-6 gap-y-8 sm:grid-cols-2 xl:grid-cols-3">
      {months.map((m, mi) => (
        <motion.div
          key={m.key}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: Math.min(mi * 0.05, 0.4) }}
        >
          <table className="w-full table-fixed border-separate border-spacing-0.5 text-center sm:border-spacing-1">
            <caption className="mb-1 text-left text-sm font-semibold capitalize">{m.label}</caption>
            <thead>
              <tr>
                {WEEKDAYS.map(([s, l]) => (
                  <th key={l} scope="col" className="text-xs font-medium text-muted">
                    <abbr title={l} className="no-underline">{s}</abbr>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {m.weeks.map((week, wi) => (
                <tr key={wi}>
                  {week.map((c, di) => {
                    if (!c) return <td key={di} />
                    if (!c.prices.length)
                      return (
                        <td key={di} className="h-14 rounded-lg align-top text-xs text-muted">
                          <span className="block pt-1">{c.day}</span>
                        </td>
                      )
                    const summary = c.prices
                      .map((p) => `${provider(p.provider).label} ${fmtPrice(p.price)}${priceExtras(p) ? ` (${priceExtras(p)})` : ''}${p.deal ? ' (chollo)' : ''}`)
                      .join(', ')
                    return (
                      <td
                        key={di}
                        className={cn(
                          `cal-lvl${c.level} h-14 rounded-lg p-0 align-top transition`,
                          c.deal && 'cal-deal',
                          selected === c.date && 'ring-2 ring-accent ring-offset-1 ring-offset-surface',
                        )}
                      >
                        <button
                          type="button"
                          onClick={() => onSelectDay(c.date)}
                          className="block w-full rounded-md pt-1 text-xs font-semibold hover:underline"
                          aria-label={`${fmtDay(c.date)}: ${summary}. Ver historial de esta fecha`}
                          aria-pressed={selected === c.date}
                        >
                          {c.day}
                        </button>
                        <div className="flex flex-col items-center pb-1">
                          {c.prices.map((p, pi) => (
                            <a
                              key={p.provider}
                              href={p.link}
                              target="_blank"
                              rel="noopener noreferrer"
                              className={cn(
                                'items-center gap-0.5 rounded px-0.5 text-[0.65rem] leading-4 whitespace-nowrap tabular-nums hover:bg-surface/70 sm:text-[0.7rem]',
                                // En móvil solo cabe el más barato de cada día (el resto, en el resumen del día).
                                pi === 0 ? 'inline-flex font-semibold' : 'hidden font-normal sm:inline-flex',
                              )}
                              aria-label={`${provider(p.provider).label}: ${fmtPrice(p.price)}${priceExtras(p) ? `, ${priceExtras(p)}` : ''} el ${fmtDay(c.date)}${p.route ? ` (${p.route})` : ''} (se abre en otra pestaña)`}
                              title={priceExtras(p) || undefined}
                            >
                              <span aria-hidden="true" className="size-1.5 shrink-0 rounded-full" style={{ background: provider(p.provider).color }} />
                              {fmtPriceShort(p.price)}
                            </a>
                          ))}
                        </div>
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </motion.div>
      ))}
    </div>
  )
}

export function CalendarLegend({ providers }: { providers: { key: string; label: string; color: string }[] }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
      {providers.map((p) => (
        <span key={p.key} className="inline-flex items-center gap-1.5">
          <span aria-hidden="true" className="size-2 rounded-full" style={{ background: p.color }} /> {p.label}
        </span>
      ))}
      <span className="inline-flex items-center gap-1.5"><span aria-hidden="true" className="cal-lvl1 size-3 rounded" /> más barato</span>
      <span className="inline-flex items-center gap-1.5"><span aria-hidden="true" className="cal-lvl4 size-3 rounded" /> más caro</span>
      <span className="inline-flex items-center gap-1.5"><span aria-hidden="true" className="cal-deal size-3 rounded" /> chollo</span>
    </div>
  )
}
