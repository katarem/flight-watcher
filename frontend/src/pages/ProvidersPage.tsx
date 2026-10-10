import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Activity, AlertTriangle, CheckCircle2, Clock, CircleSlash, ExternalLink, MinusCircle, RefreshCw, ShieldX, Stethoscope,
} from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { toast } from 'sonner'
import { errorList, post } from '@/api/client'
import { keys, useProvidersAdmin } from '@/api/queries'
import type { CandidateResult, HealthRun, HealthStatus, HealthStep, ProviderInfo } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Badge, Card, CardHeader, PageHeader } from '@/components/ui/card'
import { ErrorBox, LoadError, PageLoading } from '@/components/ui/feedback'
import { Checkbox, Field, Input } from '@/components/ui/form'
import { fmtAgo } from '@/lib/format'
import { useTitle } from '@/lib/hooks'

const LABELS: Record<HealthStatus, string> = {
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

function StatusBadge({ status }: { status: HealthStatus }) {
  const s = STATUS[status]
  return <Badge tone={s.tone}><s.icon aria-hidden="true" /> {LABELS[status]}</Badge>
}

function Steps({ steps }: { steps: HealthStep[] }) {
  return (
    <ul className="space-y-2">
      {steps.map((st) => {
        const Icon = STATUS[st.status].icon
        return (
          <li key={st.name} className="flex gap-2 text-sm">
            <Icon className="mt-0.5 size-4 shrink-0 text-muted" aria-hidden="true" />
            <div className="min-w-0">
              <p className="font-medium">
                {st.name}: <span className="font-normal">{LABELS[st.status].toLowerCase()}</span>
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

function ProviderCard({ p, onTest, testing, disabled }: {
  p: ProviderInfo
  onTest: () => void
  testing: boolean
  disabled: boolean
}) {
  return (
    <Card aria-labelledby={`prov-${p.key}`} className="relative overflow-hidden" style={{ '--c': p.color } as React.CSSProperties}>
      <span aria-hidden="true" className="absolute inset-y-0 left-0 w-1 bg-(--c)" />
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 id={`prov-${p.key}`} className="text-base font-semibold tracking-tight">{p.label}</h2>
            {p.last ? <StatusBadge status={p.last.status} /> : <Badge>sin probar</Badge>}
          </div>
          <p className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">
            <span>Cobertura: {p.coverage_label}{p.max_routes ? ` (máx. ${p.max_routes} pares)` : ''}</span>
            <span>{p.needs_browser ? 'Con navegador' : 'Sin navegador'}</span>
            <span>Pausa ≥ {p.min_interval} s entre peticiones</span>
            <span>{p.verified ? `Verificado el ${p.verified}` : 'Sin verificar contra la web real'}</span>
          </p>
          {p.notes && <p className="text-sm text-muted">{p.notes}</p>}
        </div>
        <Button size="sm" variant="secondary" onClick={onTest} loading={testing} disabled={disabled}
          aria-label={`Probar ${p.label}`}>
          {!testing && <Stethoscope />} Probar
        </Button>
      </div>
      {p.last && (
        <div className="mt-4 space-y-2 border-t border-line pt-3">
          <p className="text-xs text-muted">
            Última prueba {fmtAgo(p.last.checked_at)} · {(p.last.latency_ms / 1000).toFixed(1)} s en total
          </p>
          <Steps steps={p.last.detail} />
        </div>
      )}
    </Card>
  )
}

function CandidateCard({ c }: { c: CandidateResult }) {
  return (
    <li className="space-y-2 rounded-xl border border-line p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-medium">
          {c.label}{' '}
          <a href={c.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-0.5 text-sm text-accent underline underline-offset-2">
            {c.url.replace(/^https:\/\//, '')} <ExternalLink className="size-3.5" aria-hidden="true" />
            <span className="sr-only">(se abre en otra pestaña)</span>
          </a>
        </p>
        <StatusBadge status={c.status} />
      </div>
      <p className="text-sm text-muted">{c.notes}</p>
      <Steps steps={c.steps} />
    </li>
  )
}

export function ProvidersPage() {
  useTitle('Proveedores')
  const data = useProvidersAdmin()
  const qc = useQueryClient()
  const [origin, setOrigin] = useState('')
  const [destination, setDestination] = useState('')
  const [browser, setBrowser] = useState(false)
  const [candidates, setCandidates] = useState(true)
  const [errors, setErrors] = useState<string[]>([])
  const [testing, setTesting] = useState<string | null>(null)
  const [lastRun, setLastRun] = useState<HealthRun | null>(null)

  const run = useMutation({
    mutationFn: (key: string | null) => post<HealthRun>('/providers/health', {
      providers: key ? [key] : null, origin, destination, browser, candidates: key ? false : candidates,
    }),
    onMutate: (key) => {
      setErrors([])
      setTesting(key ?? '*')
    },
    onSuccess: (res, key) => {
      qc.invalidateQueries({ queryKey: keys.providers })
      if (!key) setLastRun(res)
      const bad = res.results.filter((r) => r.status === 'blocked' || r.status === 'error' || r.status === 'timeout')
      if (bad.length) toast.warning(`${bad.length} ${bad.length === 1 ? 'proveedor no responde bien' : 'proveedores no responden bien'}`)
      else toast.success(key ? 'Prueba terminada' : 'Todos los proveedores responden')
    },
    onError: (e) => setErrors(errorList(e)),
    onSettled: () => setTesting(null),
  })

  const revalidate = useMutation({
    mutationFn: () => post<{ started: boolean }>('/providers/revalidate'),
    onSuccess: () => toast('Revalidación lanzada', { description: 'Si una ruta se abre o se cierra, se avisa a los canales de esa vigilancia.' }),
    onError: (e) => toast.error(errorList(e)[0]),
  })

  if (data.isPending) return <PageLoading />
  if (data.isError) return <LoadError error={data.error} />

  const submit = (e: FormEvent) => {
    e.preventDefault()
    run.mutate(null)
  }
  const iata = (v: string) => v.toUpperCase().replace(/[^A-Z]/g, '').slice(0, 3)

  return (
    <>
      <PageHeader
        title="Proveedores"
        description="Comprueba desde la IP de este servidor si cada web nos deja consultar sus rutas y precios, como un healthcheck. Cada proveedor hace una sola petición a la vez y con pausas, igual que en las rondas."
        actions={
          <Button variant="secondary" onClick={() => revalidate.mutate()} loading={revalidate.isPending}>
            {!revalidate.isPending && <RefreshCw />} Revalidar rutas ahora
          </Button>
        }
      />

      <Card aria-labelledby="probar-todos" className="mb-4">
        <CardHeader id="probar-todos" title="Probar el acceso"
          description="Sin ruta, cada proveedor usa una que opera de verdad. Con ruta (aeropuertos IATA), se prueba esa en todos." />
        <form onSubmit={submit} className="space-y-4" noValidate>
          <ErrorBox errors={errors} />
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Origen de la prueba (opcional)">
              {(id) => <Input id={id} value={origin} onChange={(e) => setOrigin(iata(e.target.value))} placeholder="SVQ"
                className="font-mono uppercase" autoComplete="off" spellCheck={false} />}
            </Field>
            <Field label="Destino de la prueba (opcional)">
              {(id) => <Input id={id} value={destination} onChange={(e) => setDestination(iata(e.target.value))} placeholder="TFN"
                className="font-mono uppercase" autoComplete="off" spellCheck={false} />}
            </Field>
          </div>
          <div className="space-y-2.5">
            <Checkbox checked={candidates} onChange={setCandidates}>Probar también las aerolíneas en estudio (solo su portada)</Checkbox>
            <Checkbox checked={browser} onChange={setBrowser}>Probar también con navegador (Chromium headless, más lento)</Checkbox>
          </div>
          <Button type="submit" loading={testing === '*'} disabled={testing != null}>
            {testing !== '*' && <Activity />} Probar todos
          </Button>
        </form>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        {data.data.providers.map((p) => (
          <ProviderCard key={p.key} p={p} testing={testing === p.key} disabled={testing != null} onTest={() => run.mutate(p.key)} />
        ))}
      </div>

      {lastRun?.fx && (
        <Card aria-labelledby="divisas" className="mt-4">
          <CardHeader id="divisas" title="Cambio de divisas (BCE)" actions={<StatusBadge status={lastRun.fx.status} />}
            description="Para pasar a euros los precios en otras monedas (Wizz Air cobra en la moneda del aeropuerto de salida)." />
          <Steps steps={[lastRun.fx]} />
        </Card>
      )}

      <Card aria-labelledby="en-estudio" className="mt-4">
        <CardHeader id="en-estudio" title="En estudio"
          description="Aerolíneas que aún no son proveedores: la prueba solo pide su portada para ver si hay anti-bot antes de dedicarles un proveedor." />
        {lastRun?.candidates.length ? (
          <ul className="space-y-3">{lastRun.candidates.map((c) => <CandidateCard key={c.key} c={c} />)}</ul>
        ) : (
          <ul className="space-y-2 text-sm">
            {data.data.candidates.map((c) => (
              <li key={c.key}><span className="font-medium">{c.label}</span> <span className="text-muted">· {c.notes}</span></li>
            ))}
          </ul>
        )}
      </Card>
    </>
  )
}
