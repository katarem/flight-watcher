import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ChevronLeft, FlaskConical, ShieldAlert, Trash2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { toast } from 'sonner'
import { del, errorList, post, put } from '@/api/client'
import { keys, useProviderScript, useProviderScripts } from '@/api/queries'
import type { Coverage, ProviderScript, ScriptTestResult } from '@/api/types'
import { StatusBadge, Steps } from '@/components/provider/health'
import { Button, buttonClass } from '@/components/ui/button'
import { Card, CardHeader, PageHeader } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/dialog'
import { ErrorBox, LoadError, PageLoading } from '@/components/ui/feedback'
import { Field, FormSection, Input, Select, Switch, Textarea } from '@/components/ui/form'
import { fmtAgo, fmtDay, fmtMoney, fmtStops } from '@/lib/format'
import { useTitle } from '@/lib/hooks'

const COVERAGES: { value: Coverage; label: string; fn: string }[] = [
  { value: 'network', label: 'Red de rutas publicada', fn: 'network(api, origin)' },
  { value: 'probe', label: 'Pregunta por cada ruta', fn: 'probe(api, origin, destination)' },
  { value: 'universal', label: 'Cualquier ruta', fn: '' },
]

interface FormState {
  key: string
  label: string
  color: string
  coverage: Coverage
  max_routes: string
  health_origin: string
  health_destination: string
  link_template: string
  notes: string
  min_interval: string
  code: string
  enabled: boolean
}

const fromScript = (s: ProviderScript): FormState => ({
  key: s.key, label: s.label, color: s.color, coverage: s.coverage, max_routes: s.max_routes != null ? String(s.max_routes) : '',
  health_origin: s.health_origin, health_destination: s.health_destination, link_template: s.link_template, notes: s.notes,
  min_interval: String(s.min_interval), code: s.code ?? '', enabled: s.enabled,
})

const iata = (v: string) => v.toUpperCase().replace(/[^A-Z]/g, '').slice(0, 3)

/** Qué tiene que definir el script (el contrato), según la cobertura elegida. */
function Contract({ coverage }: { coverage: Coverage }) {
  const fn = COVERAGES.find((c) => c.value === coverage)?.fn
  return (
    <details className="rounded-xl border border-line bg-surface-2/50 p-3 text-sm">
      <summary className="cursor-pointer font-medium">El contrato: qué tiene que definir el script</summary>
      <div className="mt-3 space-y-2 text-muted">
        <p>
          <code className="text-fg">fetch_route(api, origin, destination, start, max_months)</code>: precios de
          {' '}<code>origin</code>→<code>destination</code> (aeropuertos IATA) desde <code>start</code> (fecha) durante
          {' '}<code>max_months</code> meses. Devuelve <code>{'{fecha: precio en euros}'}</code>, <code>{'{fecha: DayPrice}'}</code> o
          una lista de <code>DayPrice</code>; <code>{'{}'}</code> si no opera la ruta. Con otra moneda o con escalas:
          {' '}<code>DayPrice(día, precio, currency=&quot;GBP&quot;, stops=1)</code>.
        </p>
        {fn ? (
          <p>
            <code className="text-fg">{fn}</code>: {coverage === 'network'
              ? 'códigos IATA con vuelo directo desde origin.'
              : 'True si opera la ruta, False si no.'}
          </p>
        ) : (
          <p>Con «Cualquier ruta» no hace falta nada más.</p>
        )}
        <p>
          <code className="text-fg">api</code> hace las peticiones en el turno del proveedor (una a la vez, con la pausa
          indicada; 403/429/anti-bot = bloqueado; 404 = <code>None</code>; copia en Diagnóstico si está activo):
          {' '}<code>api.get_json(url, **params)</code>, <code>api.post_json(url, body, **params)</code>,
          {' '}<code>api.request(method, url, **kw)</code>, <code>api.session</code> (cabeceras) y <code>api.log(texto)</code>.
        </p>
        <p>
          Ya están importados <code>date</code>, <code>datetime</code>, <code>timedelta</code>, <code>re</code>, <code>json</code>,
          {' '}<code>math</code>, <code>DayPrice</code>, <code>ProviderError</code>, <code>ProviderBlocked</code> y <code>add_months</code>.
          Llama a las API con un User-Agent honesto: nada de hacerse pasar por un navegador ni de saltarse un anti-bot.
        </p>
      </div>
    </details>
  )
}

function TestResult({ res }: { res: ScriptTestResult }) {
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <StatusBadge status={res.status} />
        <span className="text-muted">{res.route} · {(res.latency_ms / 1000).toFixed(1)} s · {res.n_prices} días con precio</span>
      </div>
      <Steps steps={res.steps} />
      {res.sample.length > 0 && (
        <div className="max-h-72 overflow-auto rounded-xl border border-line" tabIndex={0} aria-label="Precios de la prueba">
          <table className="w-full text-sm">
            <caption className="sr-only">Precios devueltos por el script (próximo mes)</caption>
            <thead className="sticky top-0 bg-surface-2 text-left text-xs text-muted">
              <tr>
                <th scope="col" className="px-3 py-2 font-medium">Día</th>
                <th scope="col" className="px-3 py-2 font-medium">Precio</th>
                <th scope="col" className="px-3 py-2 font-medium">Ruta</th>
                <th scope="col" className="px-3 py-2 font-medium">Escalas</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {res.sample.map((p) => (
                <tr key={`${p.day}-${p.origin}-${p.destination}`}>
                  <td className="px-3 py-1.5">{fmtDay(p.day)}</td>
                  <td className="px-3 py-1.5 tabular-nums">{fmtMoney(p.price, p.currency)}</td>
                  <td className="px-3 py-1.5 font-mono text-xs">{p.origin}→{p.destination}</td>
                  <td className="px-3 py-1.5">{p.stops == null ? '—' : fmtStops(p.stops)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {res.logs.length > 0 && (
        <div className="space-y-1">
          <p className="text-sm font-medium">Mensajes del script (<code>api.log</code>)</p>
          <pre className="max-h-48 overflow-auto rounded-xl bg-surface-2 p-3 text-xs" tabIndex={0} aria-label="Mensajes del script">
            {res.logs.join('\n')}
          </pre>
        </div>
      )}
    </div>
  )
}

function ScriptForm({ initial, existing }: { initial: FormState; existing?: ProviderScript }) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const isNew = !existing
  const [f, setF] = useState(initial)
  const [password, setPassword] = useState('')
  const [route, setRoute] = useState({ origin: '', destination: '' })
  const [errors, setErrors] = useState<string[]>([])
  const [testErrors, setTestErrors] = useState<string[]>([])
  const [result, setResult] = useState<ScriptTestResult | null>(null)
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((s) => ({ ...s, [k]: v }))
  const refresh = () => {
    qc.invalidateQueries({ queryKey: keys.providers })
    qc.invalidateQueries({ queryKey: keys.meta })
  }

  const save = useMutation({
    mutationFn: () => {
      const body = { ...f, password }
      return isNew ? post<{ script: ProviderScript }>('/providers/scripts', body)
        : put<{ script: ProviderScript }>(`/providers/scripts/${existing.key}`, body)
    },
    onSuccess: ({ script }) => {
      refresh()
      qc.setQueryData(keys.providerScript(script.key), script)
      toast.success(isNew ? `Proveedor «${script.label}» creado` : 'Cambios guardados', {
        description: script.enabled ? 'Ya se puede elegir en las vigilancias.' : 'Está desactivado: ninguna vigilancia lo consulta.',
      })
      if (isNew) navigate(`/admin/providers/${script.key}/edit`, { replace: true })
    },
    onError: (e) => setErrors(errorList(e)),
  })

  const test = useMutation({
    mutationFn: () => post<{ result: ScriptTestResult }>('/providers/scripts/test', { ...f, ...route, password }),
    onMutate: () => {
      setTestErrors([])
      setResult(null)
    },
    onSuccess: ({ result: res }) => {
      setResult(res)
      if (res.status === 'ok') toast.success('El script funciona')
      else toast.warning('El script no ha ido bien', { description: 'Mira el resultado de la prueba.' })
    },
    onError: (e) => setTestErrors(errorList(e)),
  })

  const remove = useMutation({
    mutationFn: () => del(`/providers/scripts/${existing!.key}`),
    onSuccess: () => {
      refresh()
      toast.success(`Proveedor «${existing!.label}» eliminado`)
      navigate('/admin/providers')
    },
    onError: (e) => toast.error(errorList(e)[0]),
  })

  const submit = (e: FormEvent) => {
    e.preventDefault()
    setErrors([])
    save.mutate()
  }

  return (
    <form onSubmit={submit} className="space-y-5" noValidate>
      <ErrorBox errors={errors} />
      {existing?.error && (
        <p className="rounded-xl border border-danger/30 bg-danger/8 p-3 text-sm text-danger">
          No se carga: {existing.error}
        </p>
      )}

      <FormSection title="Proveedor" description="Cómo se verá en el panel y en los avisos, y cómo se sabe qué rutas cubre.">
        <div className="grid gap-4 sm:grid-cols-2">
          {isNew ? (
            <Field label="Clave" hint="Identificador fijo: no se puede cambiar. Minúsculas, números o guion bajo (p. ej. volotea).">
              {(id, hint) => <Input id={id} aria-describedby={hint} value={f.key} required maxLength={30} autoCapitalize="none"
                autoComplete="off" spellCheck={false} className="font-mono"
                onChange={(e) => set('key', e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, ''))} />}
            </Field>
          ) : (
            <Field label="Clave" hint="No se puede cambiar: la usan los precios guardados y los avisos.">
              {(id, hint) => <Input id={id} aria-describedby={hint} value={f.key} readOnly className="font-mono" />}
            </Field>
          )}
          <Field label="Nombre">
            {(id) => <Input id={id} value={f.label} onChange={(e) => set('label', e.target.value)} required maxLength={100}
              placeholder="Volotea" />}
          </Field>
          <Field label="Color" hint="El de su marca, en gráficas y tarjetas.">
            {(id, hint) => (
              <div className="flex gap-2">
                <input id={id} aria-describedby={hint} type="color" value={f.color} onChange={(e) => set('color', e.target.value)}
                  className="h-10 w-14 shrink-0 cursor-pointer rounded-xl border border-line bg-surface p-1 shadow-sm focus:border-accent focus:outline-none focus:ring-3 focus:ring-accent/20" />
                <Input aria-label="Color en hexadecimal" value={f.color} onChange={(e) => set('color', e.target.value)}
                  maxLength={7} className="font-mono" spellCheck={false} />
              </div>
            )}
          </Field>
          <Field label="Cobertura" hint="Qué función extra exige el contrato (ver abajo).">
            {(id, hint) => (
              <Select id={id} aria-describedby={hint} value={f.coverage} onChange={(e) => set('coverage', e.target.value as Coverage)}>
                {COVERAGES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
              </Select>
            )}
          </Field>
          {f.coverage === 'universal' && (
            <Field label="Máximo de pares de aeropuertos (opcional)" hint="Por vigilancia. Vacío = el límite general.">
              {(id, hint) => <Input id={id} aria-describedby={hint} inputMode="numeric" value={f.max_routes}
                onChange={(e) => set('max_routes', e.target.value.replace(/\D/g, ''))} />}
            </Field>
          )}
          <Field label="Pausa entre peticiones (segundos)" hint="Mínimo entre dos peticiones a esta web (más un poco al azar).">
            {(id, hint) => <Input id={id} aria-describedby={hint} inputMode="decimal" value={f.min_interval}
              onChange={(e) => set('min_interval', e.target.value)} />}
          </Field>
          <Field label="Ruta de prueba: origen" hint="Una ruta que opere de verdad (aeropuertos IATA).">
            {(id, hint) => <Input id={id} aria-describedby={hint} value={f.health_origin} placeholder="SVQ" required
              className="font-mono uppercase" autoComplete="off" spellCheck={false}
              onChange={(e) => set('health_origin', iata(e.target.value))} />}
          </Field>
          <Field label="Ruta de prueba: destino">
            {(id) => <Input id={id} value={f.health_destination} placeholder="BCN" required className="font-mono uppercase"
              autoComplete="off" spellCheck={false} onChange={(e) => set('health_destination', iata(e.target.value))} />}
          </Field>
        </div>
        <Field label="Plantilla de enlace (opcional)"
          hint="Enlace de cada fecha en los avisos. Marcadores: {origin} {destination} {date} {date_dmy} {year} {month} {day}. Se puede cambiar después en Ajustes.">
          {(id, hint) => <Input id={id} aria-describedby={hint} value={f.link_template} spellCheck={false} className="font-mono text-xs"
            placeholder="https://www.ejemplo.com/vuelos?o={origin}&d={destination}&f={date}"
            onChange={(e) => set('link_template', e.target.value)} />}
        </Field>
        <Field label="Notas (opcional)" hint="Para los administradores: de dónde salen los precios, límites conocidos…">
          {(id, hint) => <Textarea id={id} aria-describedby={hint} rows={2} maxLength={1000} value={f.notes}
            onChange={(e) => set('notes', e.target.value)} />}
        </Field>
      </FormSection>

      <FormSection title="Script" description="Código de Python que cumple el contrato de proveedor.">
        <Contract coverage={f.coverage} />
        <Field label="Código" hint="Python 3.12. Se ejecuta en el servidor al guardarlo activo, al probarlo y en cada ronda.">
          {(id, hint) => <Textarea id={id} aria-describedby={hint} value={f.code} onChange={(e) => set('code', e.target.value)}
            rows={26} spellCheck={false} autoCapitalize="none" autoComplete="off" wrap="off"
            className="font-mono text-xs leading-5 whitespace-pre" />}
        </Field>
        <Switch checked={f.enabled} onChange={(v) => set('enabled', v)} label="Proveedor activo"
          description="Desactivado no se carga: no sale en las vigilancias ni se consulta en las rondas." />
      </FormSection>

      <section aria-labelledby="confirmar" className="space-y-3 rounded-2xl border border-warn/40 bg-warn/8 p-4 sm:p-5">
        <h2 id="confirmar" className="flex items-center gap-2 text-base font-semibold">
          <ShieldAlert className="size-5 text-warn" aria-hidden="true" /> Confirma que eres tú
        </h2>
        <p className="text-sm">
          El script se ejecuta en el servidor con todos sus permisos: puede leer la base de datos y los secretos de los
          canales. Pega solo código que entiendas. Para probarlo, y para guardarlo si cambia el código o lo activas, hace
          falta tu contraseña.
        </p>
        <Field label="Tu contraseña" className="max-w-sm">
          {(id) => <Input id={id} type="password" autoComplete="current-password" value={password}
            onChange={(e) => setPassword(e.target.value)} />}
        </Field>
      </section>

      <Card aria-labelledby="probar-script">
        <CardHeader id="probar-script" title="Probar sin guardar"
          description="Carga el script del formulario y hace la prueba de acceso (cobertura y precios de un mes) desde la IP del servidor. No guarda nada." />
        <div className="space-y-4">
          <ErrorBox errors={testErrors} />
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Origen (opcional)" hint="Vacío = la ruta de prueba.">
              {(id, hint) => <Input id={id} aria-describedby={hint} value={route.origin} placeholder={f.health_origin || 'SVQ'}
                className="font-mono uppercase" autoComplete="off" spellCheck={false}
                onChange={(e) => setRoute((r) => ({ ...r, origin: iata(e.target.value) }))} />}
            </Field>
            <Field label="Destino (opcional)">
              {(id) => <Input id={id} value={route.destination} placeholder={f.health_destination || 'BCN'}
                className="font-mono uppercase" autoComplete="off" spellCheck={false}
                onChange={(e) => setRoute((r) => ({ ...r, destination: iata(e.target.value) }))} />}
            </Field>
          </div>
          <Button type="button" variant="secondary" onClick={() => test.mutate()} loading={test.isPending}>
            {!test.isPending && <FlaskConical />} Probar el script
          </Button>
          <div aria-live="polite">{result && <TestResult res={result} />}</div>
        </div>
      </Card>

      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" loading={save.isPending}>{isNew ? 'Crear proveedor' : 'Guardar cambios'}</Button>
        <Link to="/admin/providers" className={buttonClass('ghost')}>Volver</Link>
        {existing && (
          <div className="ml-auto">
            <ConfirmDialog
              trigger={<Button type="button" variant="ghost" className="text-danger"><Trash2 /> Eliminar</Button>}
              title={`¿Eliminar «${existing.label}»?`}
              description={existing.n_watches
                ? `Se quitará de ${existing.n_watches === 1 ? 'la vigilancia que lo usa' : `las ${existing.n_watches} vigilancias que lo usan`}. Sus precios y avisos guardados se conservan como histórico.`
                : 'Ninguna vigilancia lo usa. Los precios que hubiera guardado se conservan como histórico.'}
              onConfirm={() => remove.mutate()}
              loading={remove.isPending}
            />
          </div>
        )}
      </div>
    </form>
  )
}

export function ProviderScriptPage() {
  const params = useParams()
  const key = params.key ?? null
  const list = useProviderScripts()
  const existing = useProviderScript(key)
  useTitle(key ? 'Editar proveedor propio' : 'Nuevo proveedor propio')

  if (list.isPending || (key != null && existing.isPending)) return <PageLoading />
  if (list.isError) return <LoadError error={list.error} />
  if (key != null && existing.isError) return <LoadError error={existing.error} />

  const initial: FormState = existing.data ? fromScript(existing.data) : {
    key: '', label: '', color: '#64748b', coverage: 'network', max_routes: '', health_origin: '', health_destination: '',
    link_template: '', notes: '', min_interval: '1.5', code: list.data.template, enabled: true,
  }

  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader
        back={<Link to="/admin/providers" className="inline-flex items-center gap-1 text-sm text-muted hover:text-fg"><ChevronLeft className="size-4" aria-hidden="true" /> Proveedores</Link>}
        title={existing.data ? `Editar ${existing.data.label}` : 'Nuevo proveedor propio'}
        description={existing.data
          ? `Guardado ${fmtAgo(existing.data.updated_at)} por @${existing.data.updated_by}.`
          : 'Añade una aerolínea sin tocar el código de la aplicación: un script de Python que lee sus rutas y precios.'}
      />
      {!list.data.enabled ? (
        <p className="rounded-xl border border-warn/30 bg-warn/10 p-3 text-sm text-warn">
          Los proveedores propios están desactivados en este servidor (<code>PROVIDER_SCRIPTS=0</code>).
        </p>
      ) : (
        <ScriptForm key={key ?? 'new'} initial={initial} existing={existing.data} />
      )}
    </div>
  )
}
