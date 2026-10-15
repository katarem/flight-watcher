import { ArrowRight } from 'lucide-react'

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
