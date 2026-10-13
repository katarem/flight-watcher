import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ChevronLeft, Download, FlaskConical, ShieldAlert, Trash2 } from 'lucide-react'
import { useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { toast } from 'sonner'
import { API, ApiError, del, errorList, post, put, stream } from '@/api/client'
import { keys, useProvider, useProvidersAdmin } from '@/api/queries'
import type { ConsoleEvent, Coverage, KindKey, KindMeta, Provider, ScriptTestResult, StealthLevel } from '@/api/types'
import { ScriptConsole } from '@/components/provider/console'
import { StatusBadge } from '@/components/provider/health'
import { Button, buttonClass } from '@/components/ui/button'
import { PageHeader } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/dialog'
import { ErrorBox, LoadError, PageLoading } from '@/components/ui/feedback'
import { Field, FormSection, Input, Select, Switch, Textarea } from '@/components/ui/form'
import { fmtAgo, fmtClock, fmtDay, fmtMoney, fmtStops } from '@/lib/format'
import { useTitle } from '@/lib/hooks'

const COVERAGES: { value: Coverage; label: string; fn: string }[] = [
  { value: 'network', label: 'Red de rutas publicada', fn: 'network(api, origin)' },
  { value: 'probe', label: 'Pregunta por cada ruta', fn: 'probe(api, origin, destination)' },
  { value: 'universal', label: 'Cualquier ruta', fn: '' },
]

interface FormState {
  key: string
  kind: KindKey
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
  stealth: StealthLevel
}

const fromProvider = (s: Provider): FormState => ({
  key: s.key, kind: s.kind, label: s.label, color: s.color, coverage: s.coverage, max_routes: s.max_routes != null ? String(s.max_routes) : '',
  health_origin: s.health_origin, health_destination: s.health_destination, link_template: s.link_template, notes: s.notes,
  min_interval: String(s.min_interval), code: s.code ?? '', enabled: s.enabled, stealth: s.stealth,
})

/** Niveles de «Medidas anti-bot» (app/providers/stealth.py) y qué hace cada uno. */
const STEALTH: { value: StealthLevel; label: string; hint: string }[] = [
  { value: 0, label: 'Ninguna', hint: 'Peticiones normales, identificándose como Trip Watch. Lo más rápido; vale para las webs que no bloquean.' },
  {
    value: 1, label: 'Huella de Chrome y, si bloquean, Chrome',
    hint: 'Sus peticiones se hacen pasar por las de una persona con Chrome: huella TLS y HTTP/2 de Chrome, sus cabeceras en español, cookies que se conservan, visita previa a la portada y pausas más variables. Si aun así la web bloquea, repite la petición desde Chrome de verdad (más lento).',
  },
  {
    value: 2, label: 'Siempre Chrome',
    hint: 'Todas las peticiones salen de Chrome de verdad, abierto en la portada o en la página que indique el script (BROWSER_PAGE). Para webs cuyo anti-bot solo deja pasar a su propio JavaScript; es lo más lento y lo que más memoria gasta.',
  },
]

/** Código de un lugar de la ruta de prueba: IATA (3 letras) en los vuelos; de 4 a 10 letras o cifras en el resto. */
const placeCode = (kind: KindKey) => (v: string) =>
  kind === 'flight' ? v.toUpperCase().replace(/[^A-Z]/g, '').slice(0, 3) : v.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 10)

/** Qué tiene que definir el script (el contrato), según la cobertura elegida. */
function Contract({ coverage, kind }: { coverage: Coverage; kind?: KindMeta }) {
  const fn = COVERAGES.find((c) => c.value === coverage)?.fn
  const flight = !kind || kind.key === 'flight'
  const places = flight ? 'aeropuertos IATA' : `códigos de ${kind.node_label}`
  return (
    <details className="rounded-xl border border-line bg-surface-2/50 p-3 text-sm">
      <summary className="cursor-pointer font-medium">El contrato: qué tiene que definir el script</summary>
      <div className="mt-3 space-y-2 text-muted">
        <p>
          <code className="text-fg">fetch_route(api, origin, destination, start, max_months)</code>: precios de
          {' '}<code>origin</code>→<code>destination</code> ({places}) desde <code>start</code> (fecha) durante
          {' '}<code>max_months</code> meses. Devuelve <code>{'{fecha: precio en euros}'}</code>, <code>{'{fecha: DayPrice}'}</code> o
          una lista de <code>DayPrice</code>; <code>{'{}'}</code> si no opera la ruta. Con otra moneda o con escalas:
          {' '}<code>DayPrice(día, precio, currency=&quot;GBP&quot;, stops=1)</code>; con la hora de salida y de llegada, si la web
          las da: <code>DayPrice(día, precio, departure=&quot;06:35&quot;, arrival=&quot;08:10&quot;)</code> (también
          {' '}<code>datetime</code>; una llegada anterior a la salida es del día siguiente). Si además acepta
          {' '}<code>max_stops=None</code>, recibe el máximo de escalas de la vigilancia y filtra él mismo.
        </p>
        {fn ? (
          <p>
            <code className="text-fg">{fn}</code>: {coverage === 'network'
              ? `${flight ? 'códigos IATA' : places} con trayecto directo desde origin.`
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
          {' '}<code>api.log</code> y <code>print</code> salen en la consola de la prueba, junto a cada petición y su respuesta.
        </p>
        <p>
          Ya están importados <code>date</code>, <code>datetime</code>, <code>timedelta</code>, <code>re</code>, <code>json</code>,
          {' '}<code>math</code>, <code>DayPrice</code>, <code>ProviderError</code>, <code>ProviderBlocked</code> y <code>add_months</code>.
          Las peticiones llevan un User-Agent que dice quiénes somos (<code>trip-watch</code>), salvo con medidas anti-bot.
        </p>
        <p>
          Opcional: <code className="text-fg">BROWSER_PAGE = &quot;https://…&quot;</code>, la página de la web que abre Chrome
          cuando las peticiones van por él (si no, la portada del dominio de la API). Hace falta si la API solo acepta
          peticiones desde otra página o el anti-bot solo corre en ella.
        </p>
      </div>
    </details>
  )
}

function TestResult({ res }: { res: ScriptTestResult }) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <StatusBadge status={res.status} />
        <span className="text-muted">{res.route} · {(res.latency_ms / 1000).toFixed(1)} s · {res.n_prices} días con precio</span>
      </div>
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
                <th scope="col" className="px-3 py-2 font-medium">Horas</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {res.sample.map((p) => (
                <tr key={`${p.day}-${p.origin}-${p.destination}`}>
                  <td className="px-3 py-1.5">{fmtDay(p.day)}</td>
                  <td className="px-3 py-1.5 tabular-nums">{fmtMoney(p.price, p.currency)}</td>
                  <td className="px-3 py-1.5 font-mono text-xs">{p.origin}→{p.destination}</td>
                  <td className="px-3 py-1.5">{p.stops == null ? '—' : fmtStops(p.stops)}</td>
                  <td className="px-3 py-1.5 whitespace-nowrap tabular-nums">{fmtClock(p.departs_at, p.arrives_at) || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

type TestEvent = ConsoleEvent | { result: ScriptTestResult }

function ProviderForm({ initial, existing, editable, kinds }: {
  initial: FormState
  existing?: Provider
  editable: boolean
  kinds: KindMeta[]
}) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const isNew = !existing
  const [f, setF] = useState(initial)
  const [password, setPassword] = useState('')
  const [route, setRoute] = useState({ origin: '', destination: '' })
  const [errors, setErrors] = useState<string[]>([])
  const [testErrors, setTestErrors] = useState<string[]>([])
  const [result, setResult] = useState<ScriptTestResult | null>(null)
  const [events, setEvents] = useState<ConsoleEvent[]>([])
  const [consoleOpen, setConsoleOpen] = useState(false)
  const received = useRef(0)
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((s) => ({ ...s, [k]: v }))
  const kind = kinds.find((k) => k.key === f.kind)
  const code = placeCode(f.kind)
  const nodeHint = f.kind === 'flight' ? 'aeropuertos IATA' : `código de ${kind?.node_label ?? 'lugar'}`
  const refresh = () => {
    qc.invalidateQueries({ queryKey: keys.providers })
    qc.invalidateQueries({ queryKey: keys.meta })
  }

  const save = useMutation({
    mutationFn: () => {
      const body = { ...f, password }
      return isNew ? post<{ provider: Provider }>('/providers', body)
        : put<{ provider: Provider }>(`/providers/${existing.key}`, body)
    },
    onSuccess: ({ provider }) => {
      refresh()
      qc.setQueryData(keys.provider(provider.key), provider)
      toast.success(isNew ? `Proveedor «${provider.label}» creado` : 'Cambios guardados', {
        description: provider.enabled ? 'Ya se puede elegir en las vigilancias.' : 'Está desactivado: ninguna vigilancia lo consulta.',
      })
      if (isNew) navigate(`/admin/providers/${provider.key}/edit`, { replace: true })
    },
    onError: (e) => setErrors(errorList(e)),
  })

  // La prueba responde en streaming: cada línea de la consola llega en cuanto ocurre y el resultado, al final.
  const test = useMutation({
    mutationFn: async () => {
      let final = null as ScriptTestResult | null
      await stream<TestEvent>('/providers/test', { ...f, ...route, password }, (ev) => {
        if ('result' in ev) final = ev.result
        else {
          received.current += 1
          setEvents((xs) => [...xs, ev])
        }
      })
      if (!final) throw new ApiError(0, ['La prueba no ha terminado: se ha cortado la conexión con el servidor.'])
      return final
    },
    onMutate: () => {
      setTestErrors([])
      setResult(null)
      setEvents([])
      received.current = 0
      setConsoleOpen(true)
    },
    onSuccess: (res) => {
      setResult(res)
      if (res.status === 'ok') toast.success('El script funciona')
      else toast.warning('El script no ha ido bien', { description: 'Mira la consola de la prueba.' })
    },
    onError: (e) => {
      setTestErrors(errorList(e))
      if (!received.current) setConsoleOpen(false)
    },
  })

  const remove = useMutation({
    mutationFn: () => del(`/providers/${existing!.key}`),
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
          <Field label="Tipo"
            hint={existing?.n_watches
              ? 'No se puede cambiar mientras lo use alguna vigilancia.'
              : kind && !kind.available
                ? `Aún no hay vigilancias de ${kind.plural} (llegan en la ${kind.since}), pero ya se puede escribir y probar.`
                : 'Qué transporte vende: solo sale en las vigilancias de ese transporte.'}>
            {(id, hint) => (
              <Select id={id} aria-describedby={hint} value={f.kind} disabled={!!existing?.n_watches}
                onChange={(e) => set('kind', e.target.value as KindKey)}>
                {kinds.map((k) => <option key={k.key} value={k.key}>{k.label}{k.available ? '' : ` (vigilancias en la ${k.since})`}</option>)}
              </Select>
            )}
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
            <Field label="Máximo de combinaciones de origen y destino (opcional)" hint="Por vigilancia. Vacío = el límite general.">
              {(id, hint) => <Input id={id} aria-describedby={hint} inputMode="numeric" value={f.max_routes}
                onChange={(e) => set('max_routes', e.target.value.replace(/\D/g, ''))} />}
            </Field>
          )}
          <Field label="Pausa entre peticiones (segundos)" hint="Mínimo entre dos peticiones a esta web (más un poco al azar).">
            {(id, hint) => <Input id={id} aria-describedby={hint} inputMode="decimal" value={f.min_interval}
              onChange={(e) => set('min_interval', e.target.value)} />}
          </Field>
          <Field label="Ruta de prueba: origen" hint={`Una ruta que opere de verdad (${nodeHint}).`}>
            {(id, hint) => <Input id={id} aria-describedby={hint} value={f.health_origin} placeholder="SVQ" required
              className="font-mono uppercase" autoComplete="off" spellCheck={false}
              onChange={(e) => set('health_origin', code(e.target.value))} />}
          </Field>
          <Field label="Ruta de prueba: destino">
            {(id) => <Input id={id} value={f.health_destination} placeholder="BCN" required className="font-mono uppercase"
              autoComplete="off" spellCheck={false} onChange={(e) => set('health_destination', code(e.target.value))} />}
          </Field>
        </div>
        <Field label="Plantilla de enlace (opcional)"
          hint="Enlace de cada fecha en los avisos. Marcadores: {origin} {destination} {date} {date_dmy} {year} {month} {day}. Se puede cambiar después en Ajustes.">
          {(id, hint) => <Input id={id} aria-describedby={hint} value={f.link_template} spellCheck={false} className="font-mono text-xs"
            placeholder="https://www.ejemplo.com/vuelos?o={origin}&d={destination}&f={date}"
            onChange={(e) => set('link_template', e.target.value)} />}
        </Field>
        <Field label="Medidas anti-bot"
          hint={`${STEALTH.find((s) => s.value === f.stealth)?.hint ?? ''} No resuelven CAPTCHA que pidan intervención.`}>
          {(id, hint) => (
            <Select id={id} aria-describedby={hint} value={f.stealth}
              onChange={(e) => set('stealth', Number(e.target.value) as StealthLevel)}>
              {STEALTH.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </Select>
          )}
        </Field>
        <Field label="Notas (opcional)" hint="Para los administradores: de dónde salen los precios, límites conocidos…">
          {(id, hint) => <Textarea id={id} aria-describedby={hint} rows={2} maxLength={1000} value={f.notes}
            onChange={(e) => set('notes', e.target.value)} />}
        </Field>
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

      <FormSection title="Script" description="Código de Python que cumple el contrato de proveedor.">
        <Contract coverage={f.coverage} kind={kind} />
        {!editable && (
          <p className="rounded-xl border border-warn/30 bg-warn/10 p-3 text-sm text-warn">
            En este servidor no se puede cambiar ni probar el código desde el panel (<code>PROVIDER_SCRIPTS=0</code>).
            Sí puedes cambiar el nombre, la plantilla de enlace o desactivarlo.
          </p>
        )}
        <section aria-labelledby="probar-script" className="space-y-3 rounded-xl border border-line p-3 sm:p-4">
          <div>
            <h3 id="probar-script" className="text-sm font-semibold">Probar sin guardar</h3>
            <p className="text-xs text-muted">
              Carga el script de abajo y hace la prueba de acceso (cobertura y precios de un mes) desde la IP del
              servidor. La consola cuenta cada paso y cada petición mientras ocurren. No guarda nada.
            </p>
          </div>
          <ErrorBox errors={testErrors} />
          <div className="flex flex-wrap items-end gap-3">
            <Field label="Origen (opcional)" className="w-36">
              {(id) => <Input id={id} value={route.origin} placeholder={f.health_origin || 'SVQ'}
                className="font-mono uppercase" autoComplete="off" spellCheck={false}
                onChange={(e) => setRoute((r) => ({ ...r, origin: code(e.target.value) }))} />}
            </Field>
            <Field label="Destino (opcional)" className="w-36">
              {(id) => <Input id={id} value={route.destination} placeholder={f.health_destination || 'BCN'}
                className="font-mono uppercase" autoComplete="off" spellCheck={false}
                onChange={(e) => setRoute((r) => ({ ...r, destination: code(e.target.value) }))} />}
            </Field>
            <Button type="button" variant="secondary" onClick={() => test.mutate()} loading={test.isPending} disabled={!editable}>
              {!test.isPending && <FlaskConical />} Probar el script
            </Button>
          </div>
          {consoleOpen && <ScriptConsole events={events} running={test.isPending} onClose={() => setConsoleOpen(false)} />}
          <div aria-live="polite">{result && <TestResult res={result} />}</div>
        </section>
        <Field label="Código" hint="Python 3.12. Se ejecuta en el servidor al guardarlo activo, al probarlo y en cada ronda.">
          {(id, hint) => <Textarea id={id} aria-describedby={hint} value={f.code} onChange={(e) => set('code', e.target.value)}
            rows={26} spellCheck={false} autoCapitalize="none" autoComplete="off" wrap="off" readOnly={!editable}
            className="font-mono text-xs leading-5 whitespace-pre" />}
        </Field>
        <Switch checked={f.enabled} onChange={(v) => set('enabled', v)} label="Proveedor activo"
          description="Desactivado no se carga: no sale en las vigilancias ni se consulta en las rondas." />
      </FormSection>

      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" loading={save.isPending}>{isNew ? 'Crear proveedor' : 'Guardar cambios'}</Button>
        <Link to="/admin/providers" className={buttonClass('ghost')}>Volver</Link>
        {existing && (
          <div className="ml-auto flex gap-2">
            <a href={`${API}/providers/export?keys=${encodeURIComponent(existing.key)}`} download className={buttonClass('ghost')}>
              <Download aria-hidden="true" /> Exportar
            </a>
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

const SOURCE_LABEL = (s: Provider) => s.source ? <> · importado de <span className="break-all">{s.source}</span></> : null

export function ProviderFormPage() {
  const params = useParams()
  const key = params.key ?? null
  const list = useProvidersAdmin()
  const existing = useProvider(key)
  useTitle(key ? 'Editar proveedor' : 'Nuevo proveedor')

  if (list.isPending || (key != null && existing.isPending)) return <PageLoading />
  if (list.isError) return <LoadError error={list.error} />
  if (key != null && existing.isError) return <LoadError error={existing.error} />

  const initial: FormState = existing.data ? fromProvider(existing.data) : {
    key: '', kind: 'flight', label: '', color: '#64748b', coverage: 'network', max_routes: '', health_origin: '', health_destination: '',
    link_template: '', notes: '', min_interval: '1.5', code: list.data.template, enabled: true, stealth: 0,
  }

  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader
        back={<Link to="/admin/providers" className="inline-flex items-center gap-1 text-sm text-muted hover:text-fg"><ChevronLeft className="size-4" aria-hidden="true" /> Proveedores</Link>}
        title={existing.data ? `Editar ${existing.data.label}` : 'Nuevo proveedor'}
        description={existing.data
          ? <>Guardado {fmtAgo(existing.data.updated_at)} por @{existing.data.updated_by}{SOURCE_LABEL(existing.data)}.</>
          : 'Un script de Python que lee las rutas y los precios de una web. También puedes importar uno desde un enlace o un archivo.'}
      />
      {!existing.data && !list.data.editable ? (
        <p className="rounded-xl border border-warn/30 bg-warn/10 p-3 text-sm text-warn">
          En este servidor no se pueden crear proveedores desde el panel (<code>PROVIDER_SCRIPTS=0</code>).
        </p>
      ) : (
        <ProviderForm key={key ?? 'new'} initial={initial} existing={existing.data} editable={list.data.editable}
          kinds={list.data.kinds} />
      )}
    </div>
  )
}
