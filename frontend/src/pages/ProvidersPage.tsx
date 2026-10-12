import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Activity, Download, Pencil, Plus, RefreshCw, ShieldCheck, Stethoscope, Upload } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { toast } from 'sonner'
import { Link } from 'react-router'
import { API, errorList, post } from '@/api/client'
import { keys, useProvidersAdmin } from '@/api/queries'
import type { HealthRun, Provider } from '@/api/types'
import { StatusBadge, Steps } from '@/components/provider/health'
import { Button, buttonClass } from '@/components/ui/button'
import { Badge, Card, CardHeader, PageHeader } from '@/components/ui/card'
import { ErrorBox, LoadError, PageLoading } from '@/components/ui/feedback'
import { Checkbox, Field, Input } from '@/components/ui/form'
import { fmtAgo } from '@/lib/format'
import { useTitle } from '@/lib/hooks'

function ProviderCard({ p, onTest, testing, disabled, selected, onSelect }: {
  p: Provider
  onTest: () => void
  testing: boolean
  disabled: boolean
  selected: boolean
  onSelect: (v: boolean) => void
}) {
  return (
    <Card aria-labelledby={`prov-${p.key}`} className="relative overflow-hidden" style={{ '--c': p.color } as React.CSSProperties}>
      <span aria-hidden="true" className="absolute inset-y-0 left-0 w-1 bg-(--c)" />
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 gap-3">
          <Checkbox checked={selected} onChange={onSelect} className="mt-1">
            <span className="sr-only">Elegir {p.label} para exportar</span>
          </Checkbox>
          <div className="min-w-0 space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 id={`prov-${p.key}`} className="text-base font-semibold tracking-tight">{p.label}</h2>
              <span className="font-mono text-xs text-muted">{p.key}</span>
              {p.error ? <Badge tone="danger">No carga</Badge> : !p.enabled ? <Badge>Desactivado</Badge> : null}
              {p.stealth > 0 && (
                <Badge tone="accent"><ShieldCheck aria-hidden="true" /> {p.stealth === 2 ? 'Siempre Chrome' : 'Anti-bot'}</Badge>
              )}
              {p.loaded && (p.last ? <StatusBadge status={p.last.status} /> : <Badge>sin probar</Badge>)}
            </div>
            <p className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">
              <span>Cobertura: {p.coverage_label}{p.max_routes ? ` (máx. ${p.max_routes} pares)` : ''}</span>
              {p.stops_filter && <span>Filtra por escalas</span>}
              <span>Pausa ≥ {p.min_interval} s entre peticiones</span>
              <span>{p.n_watches} {p.n_watches === 1 ? 'vigilancia' : 'vigilancias'}</span>
              <span>Guardado {fmtAgo(p.updated_at)} por @{p.updated_by}</span>
            </p>
            {p.error && <p className="break-words text-sm text-danger">{p.error}</p>}
            {p.notes && <p className="text-sm text-muted">{p.notes}</p>}
          </div>
        </div>
        <div className="flex gap-2">
          <Link to={`/admin/providers/${p.key}/edit`} className={buttonClass('ghost', 'sm')} aria-label={`Editar ${p.label}`}>
            <Pencil /> Editar
          </Link>
          {p.loaded && (
            <Button size="sm" variant="secondary" onClick={onTest} loading={testing} disabled={disabled} aria-label={`Probar ${p.label}`}>
              {!testing && <Stethoscope />} Probar
            </Button>
          )}
        </div>
      </div>
      {p.loaded && p.last && (
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

export function ProvidersPage() {
  useTitle('Proveedores')
  const data = useProvidersAdmin()
  const qc = useQueryClient()
  const [origin, setOrigin] = useState('')
  const [destination, setDestination] = useState('')
  const [errors, setErrors] = useState<string[]>([])
  const [testing, setTesting] = useState<string | null>(null)
  const [lastRun, setLastRun] = useState<HealthRun | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())

  const run = useMutation({
    mutationFn: (key: string | null) => post<HealthRun>('/providers/health', {
      providers: key ? [key] : null, origin, destination,
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

  const { providers, editable } = data.data
  const chosen = providers.filter((p) => selected.has(p.key))
  const toggle = (key: string, on: boolean) => setSelected((s) => {
    const next = new Set(s)
    if (on) next.add(key)
    else next.delete(key)
    return next
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    run.mutate(null)
  }
  const iata = (v: string) => v.toUpperCase().replace(/[^A-Z]/g, '').slice(0, 3)
  const exportUrl = (keys: string[]) => `${API}/providers/export${keys.length ? `?keys=${encodeURIComponent(keys.join(','))}` : ''}`

  return (
    <>
      <PageHeader
        title="Proveedores"
        description="Cada proveedor es un script de Python que lee las rutas y los precios de una web. Puedes crearlos, editarlos, importarlos desde un enlace o un archivo y exportarlos para usarlos en otro panel."
        actions={
          <>
            {editable && (
              <>
                <Link to="/admin/providers/new" className={buttonClass('primary')}><Plus /> Nuevo proveedor</Link>
                <Link to="/admin/providers/import" className={buttonClass('secondary')}><Upload /> Importar</Link>
              </>
            )}
            <Button variant="secondary" onClick={() => revalidate.mutate()} loading={revalidate.isPending}>
              {!revalidate.isPending && <RefreshCw />} Revalidar rutas ahora
            </Button>
          </>
        }
      />

      {!editable && (
        <p className="mb-4 rounded-xl border border-warn/30 bg-warn/10 p-3 text-sm text-warn">
          En este servidor no se puede crear, importar ni cambiar el código de los proveedores desde el panel
          (variable <code>PROVIDER_SCRIPTS=0</code>). Los que hay siguen funcionando.
        </p>
      )}

      <Card aria-labelledby="probar-todos" className="mb-4">
        <CardHeader id="probar-todos" title="Probar el acceso"
          description="Comprueba desde la IP de este servidor si cada web nos deja consultar sus rutas y precios, como un healthcheck. Sin ruta, cada proveedor usa la suya; con ruta (aeropuertos IATA), se prueba esa en todos." />
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
          <Button type="submit" loading={testing === '*'} disabled={testing != null || !providers.some((p) => p.loaded)}>
            {testing !== '*' && <Activity />} Probar todos
          </Button>
        </form>
      </Card>

      {providers.length > 0 && (
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3" role="group" aria-label="Exportar proveedores">
          <Checkbox checked={chosen.length === providers.length}
            onChange={(on) => setSelected(new Set(on ? providers.map((p) => p.key) : []))}>
            Elegir todos ({chosen.length} de {providers.length})
          </Checkbox>
          <div className="flex flex-wrap gap-2">
            {chosen.length ? (
              <a href={exportUrl(chosen.map((p) => p.key))} download className={buttonClass('secondary', 'sm')}>
                <Download aria-hidden="true" /> Exportar los elegidos ({chosen.length})
              </a>
            ) : (
              <Button size="sm" variant="secondary" disabled><Download /> Exportar los elegidos</Button>
            )}
            <a href={exportUrl([])} download className={buttonClass('ghost', 'sm')}>
              <Download aria-hidden="true" /> Exportar todos
            </a>
          </div>
        </div>
      )}

      {providers.length === 0 ? (
        <Card aria-labelledby="sin-proveedores">
          <CardHeader id="sin-proveedores" title="No hay proveedores"
            description="Sin proveedores no se consulta ninguna web. Importa los del catálogo (Vueling, Ryanair…) o crea uno." />
          {editable && <Link to="/admin/providers/import" className={buttonClass('primary')}><Upload /> Importar proveedores</Link>}
        </Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {providers.map((p) => (
            <ProviderCard key={p.key} p={p} testing={testing === p.key} disabled={testing != null}
              onTest={() => run.mutate(p.key)} selected={selected.has(p.key)} onSelect={(on) => toggle(p.key, on)} />
          ))}
        </div>
      )}

      {lastRun?.fx && (
        <Card aria-labelledby="divisas" className="mt-4">
          <CardHeader id="divisas" title="Cambio de divisas (BCE)" actions={<StatusBadge status={lastRun.fx.status} />}
            description="Para pasar a euros los precios en otras monedas (por ejemplo, Wizz Air cobra en la moneda del aeropuerto de salida)." />
          <Steps steps={[lastRun.fx]} />
        </Card>
      )}
    </>
  )
}
