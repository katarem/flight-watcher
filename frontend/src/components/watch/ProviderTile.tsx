import { AlertTriangle, ArrowUpRight, Sparkles } from 'lucide-react'
import type { ProviderStat } from '@/api/types'
import { Badge } from '@/components/ui/card'
import { cn } from '@/lib/cn'
import { fmtAgo, fmtDay, fmtPrice } from '@/lib/format'

/** Mejor precio actual de una web dentro de una vigilancia. */
export function ProviderTile({ stat, detail, className }: { stat: ProviderStat; detail?: boolean; className?: string }) {
  const best = stat.best
  return (
    <div
      className={cn('relative overflow-hidden rounded-xl border border-line bg-surface-2/50 p-3.5 pl-4', className)}
      style={{ '--c': stat.color } as React.CSSProperties}
    >
      <span aria-hidden="true" className="absolute inset-y-0 left-0 w-1 bg-(--c)" />
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium">{stat.label}</span>
        {best?.deal && (
          <Badge tone="deal">
            <Sparkles aria-hidden="true" /> chollo
          </Badge>
        )}
      </div>
      {best ? (
        <>
          <p className="mt-1 text-3xl font-semibold tracking-tight tabular-nums">{fmtPrice(best.price)}</p>
          <p className="text-sm text-muted">
            {fmtDay(best.flight_date)}
            {best.route && <span className="ml-1 font-mono text-xs">· {best.route}</span>}
          </p>
          {(() => {
            const facts = [
              detail && stat.median != null && `Mediana actual ${fmtPrice(stat.median)}`,
              stat.base != null && `habitual ≈ ${fmtPrice(stat.base)}`,
              detail && stat.count != null && `${stat.count} fechas con precio`,
            ].filter(Boolean)
            return facts.length > 0 && <p className="mt-1 text-xs text-muted">{facts.join(' · ')}</p>
          })()}
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
            <a
              href={best.link}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-0.5 text-sm font-medium text-accent hover:underline"
            >
              Ver esa fecha en {stat.label}
              <ArrowUpRight className="size-3.5" aria-hidden="true" />
              <span className="sr-only">(se abre en otra pestaña)</span>
            </a>
            <span className="text-xs text-muted" title={best.checked_at}>Actualizado {fmtAgo(best.checked_at)}</span>
          </div>
        </>
      ) : (
        <p className="mt-2 text-sm text-muted">Sin datos todavía</p>
      )}
      {stat.run && !stat.run.ok && (
        <p className="mt-2 flex gap-1.5 text-xs text-danger">
          <AlertTriangle className="mt-px size-3.5 shrink-0" aria-hidden="true" />
          <span className="line-clamp-3">{stat.run.error}</span>
        </p>
      )}
    </div>
  )
}
