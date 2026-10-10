import { AlertTriangle, CheckCircle2, CircleSlash, Clock, MinusCircle, ShieldX } from 'lucide-react'
import type { HealthStatus, HealthStep } from '@/api/types'
import { Badge } from '@/components/ui/card'

/** Piezas de la prueba de acceso a proveedores (zona Proveedores y editor de proveedores propios). */
export const HEALTH_LABELS: Record<HealthStatus, string> = {
  ok: 'Accesible', empty: 'Accesible, sin precios', blocked: 'Bloqueado', error: 'Con errores', timeout: 'Sin respuesta',
  skipped: 'Omitido',
}

const STATUS = {
  ok: { tone: 'deal', icon: CheckCircle2 },
  empty: { tone: 'warn', icon: MinusCircle },
  blocked: { tone: 'danger', icon: ShieldX },
  error: { tone: 'danger', icon: AlertTriangle },
  timeout: { tone: 'warn', icon: Clock },
  skipped: { tone: 'neutral', icon: CircleSlash },
} as const

export function StatusBadge({ status }: { status: HealthStatus }) {
  const s = STATUS[status]
  return <Badge tone={s.tone}><s.icon aria-hidden="true" /> {HEALTH_LABELS[status]}</Badge>
}

export function Steps({ steps }: { steps: HealthStep[] }) {
  return (
    <ul className="space-y-2">
      {steps.map((st) => {
        const Icon = STATUS[st.status].icon
        return (
          <li key={st.name} className="flex gap-2 text-sm">
            <Icon className="mt-0.5 size-4 shrink-0 text-muted" aria-hidden="true" />
            <div className="min-w-0">
              <p className="font-medium">
                {st.name}: <span className="font-normal">{HEALTH_LABELS[st.status].toLowerCase()}</span>
                <span className="ml-1.5 text-xs text-muted tabular-nums">
                  {st.route && `${st.route} · `}{(st.ms / 1000).toFixed(1)} s{st.http_status ? ` · HTTP ${st.http_status}` : ''}
                </span>
              </p>
              <p className="break-words text-muted">{st.detail}</p>
            </div>
          </li>
        )
      })}
    </ul>
  )
}
