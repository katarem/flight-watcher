import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, ArrowLeftRight, CheckCircle2, Clock, RefreshCw, Trash2, XCircle } from 'lucide-react'
import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'
import { toast } from 'sonner'
import { ApiError, del, errorList, get, post, put } from '@/api/client'
import { keys, useChannels, useMeta, useWatch } from '@/api/queries'
import type { Place, ProviderMeta, RouteCheck, RouteCheckProvider, Watch } from '@/api/types'
import { Button, buttonClass } from '@/components/ui/button'
import { Badge, PageHeader } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/dialog'
import { ErrorBox, LoadError, PageLoading, Spinner } from '@/components/ui/feedback'
import { Checkbox, Field, FormSection, Input, Select, Switch } from '@/components/ui/form'
import { PlaceCombobox } from '@/components/watch/PlaceCombobox'
import { cn } from '@/lib/cn'
import { useTitle } from '@/lib/hooks'

interface FormState {
  name: string
  origin: string
  destination: string
  originPlace: Place | null
  destinationPlace: Place | null
  providers: string[]
  max_price: string
  discount_pct: string
  date_from: string
  date_to: string
  max_stops: string
  enabled: boolean
  channel_ids: number[]
}

const fromWatch = (w: Watch): FormState => ({
  name: w.name, origin: w.origin, destination: w.destination, originPlace: w.origin_place,
  destinationPlace: w.destination_place, providers: w.providers,
  max_price: w.max_price != null ? String(w.max_price) : '', discount_pct: String(Math.round(w.discount_pct)),
  date_from: w.date_from ?? '', date_to: w.date_to ?? '', max_stops: w.max_stops == null ? '' : String(w.max_stops),
  enabled: w.enabled, channel_ids: w.channel_ids,
})

const toggle = <T,>(list: T[], v: T, on: boolean) => (on ? [...new Set([...list, v])] : list.filter((x) => x !== v))

/** ¿Hay un lugar que comprobar? (elegido de la lista o un código escrito a mano). */
const ready = (code: string, place: Place | null) => !!place || /^[A-Z]{2,3}$/.test(code)

const STATUS_UI = {
  ok: { icon: CheckCircle2, tone: 'text-deal' },
  none: { icon: XCircle, tone: 'text-muted' },
  too_many: { icon: XCircle, tone: 'text-muted' },
  error: { icon: AlertTriangle, tone: 'text-warn' },
  timeout: { icon: Clock, tone: 'text-warn' },
} as const

/** Una web con su casilla y lo que dice la comprobación de la ruta. */
function ProviderOption({ p, checked, onChange, result, checking, kept }: {
  p: ProviderMeta
  checked: boolean
  onChange: (v: boolean) => void
  result?: RouteCheckProvider
  checking: boolean
  kept: boolean
}) {
  const id = useId()
  const unavailable = result && (result.status === 'none' || result.status === 'too_many')
  const ui = result ? STATUS_UI[result.status] : null
  return (
    <div className={cn('rounded-xl border p-3 transition', checked ? 'border-accent bg-accent-soft/50' : 'border-line',
      unavailable && !kept && 'border-dashed')}>
      <Checkbox checked={checked && !(unavailable && !kept)} onChange={onChange} disabled={!!unavailable && !kept} describedBy={id}>
        <span aria-hidden="true" className="size-2.5 rounded-full" style={{ background: p.color }} />
        {p.label}
        {p.coverage === 'universal' && <Badge>cualquier aerolínea</Badge>}
      </Checkbox>
      <p id={id} className="mt-1.5 flex gap-1.5 pl-7.5 text-xs text-muted">
        {checking ? (
          <><Spinner className="size-3.5 shrink-0" /> Comprobando si opera la ruta…</>
        ) : result && ui ? (
          <>
            <ui.icon className={cn('mt-px size-3.5 shrink-0', ui.tone)} aria-hidden="true" />
            <span>
              {result.reason}
              {unavailable && kept && ' Se mantiene en pausa y se revisa cada semana por si vuelve a operar (rutas de temporada).'}
              {(result.status === 'error' || result.status === 'timeout') && ' Puedes elegirla igualmente: se comprobará más adelante.'}
            </span>
          </>
        ) : (
          <span>Elige origen y destino para ver si opera la ruta.</span>
        )}
      </p>
    </div>
  )
}

function WatchForm({ initial, watchId, trips = [], forTrip }: {
  initial: FormState
  watchId?: number
  /** Viajes de los que es tramo (se borran con ella). */
  trips?: { id: number; name: string }[]
  /** Vigilancia de ida de un viaje en preparación: al crear esta (la vuelta), se vuelve al viaje. */
  forTrip?: string | null
}) {
  const isNew = watchId == null
  const meta = useMeta().data
  const channelData = useChannels('').data
  const channels = channelData ?? []
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [f, setF] = useState(initial)
  const [errors, setErrors] = useState<string[]>([])
  const [swaps, setSwaps] = useState(0)
  const errorRef = useRef<HTMLDivElement>(null)
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((s) => ({ ...s, [k]: v }))

  // Comprobación de la ruta: qué webs la operan (en paralelo en el servidor, con tiempo límite por web).
  const routeKey = ready(f.origin, f.originPlace) && ready(f.destination, f.destinationPlace) ? `${f.origin}|${f.destination}` : ''
  const check = useQuery({
    queryKey: ['route-check', routeKey],
    queryFn: () => post<RouteCheck>('/route-check', { origin: f.origin, destination: f.destination }),
    enabled: !!routeKey,
    staleTime: 5 * 60_000,
    retry: false,
  })
  const results = new Map((check.data?.providers ?? []).map((r) => [r.key, r]))
  const kept = new Set(isNew ? [] : initial.providers)

  // Vigilancia nueva: se marcan las aerolíneas que operan la ruta (hasta que el usuario toque las casillas).
  const touched = useRef(!isNew)
  const lastAuto = useRef('')
  useEffect(() => {
    const data = check.data
    if (!data || touched.current || lastAuto.current === routeKey) return
    lastAuto.current = routeKey
    setF((s) => ({ ...s, providers: data.providers.filter((r) => r.ok && r.coverage !== 'universal').map((r) => r.key) }))
  }, [check.data, routeKey])

  // Canales nuevos: por defecto, todos los activos (como en el panel anterior).
  const defaulted = useRef(!isNew)
  useEffect(() => {
    if (!defaulted.current && channelData?.length) {
      defaulted.current = true
      setF((s) => ({ ...s, channel_ids: channelData.filter((c) => c.enabled).map((c) => c.id) }))
    }
  }, [channelData])

  const save = useMutation({
    mutationFn: () => {
      // Las que seguro no operan la ruta no se envían (salvo las que ya tenía: rutas de temporada).
      const providers = f.providers.filter((k) => {
        const r = results.get(k)
        return kept.has(k) || !r || (r.status !== 'none' && r.status !== 'too_many')
      })
      const body = {
        name: f.name, origin: f.origin, destination: f.destination, providers, max_price: f.max_price || null,
        discount_pct: f.discount_pct, date_from: f.date_from || null, date_to: f.date_to || null,
        max_stops: f.max_stops, enabled: f.enabled, channel_ids: f.channel_ids,
      }
      return isNew ? post<{ watch: Watch }>('/watches', body) : put<{ watch: Watch }>(`/watches/${watchId}`, body)
    },
    onSuccess: ({ watch }) => {
      qc.invalidateQueries({ queryKey: keys.watches })
      toast.success(isNew ? 'Vigilancia creada' : 'Cambios guardados', {
        description: isNew ? 'Pulsa «Comprobar ahora» para traer los primeros precios.' : undefined,
      })
      navigate(isNew && forTrip ? `/trips/new?outbound=${forTrip}&return=${watch.id}` : `/watches/${watch.id}`)
    },
    onError: (e) => {
      setErrors(errorList(e))
      requestAnimationFrame(() => errorRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' }))
    },
  })

  const remove = useMutation({
    mutationFn: () => del(`/watches/${watchId}`),
    onSuccess: () => {
      qc.removeQueries({ queryKey: keys.watch(watchId!) })
      qc.invalidateQueries({ queryKey: keys.watches })
      toast.success('Vigilancia eliminada junto con su histórico')
      navigate('/')
    },
    onError: (e) => toast.error(errorList(e)[0]),
  })

  const submit = (e: FormEvent) => {
    e.preventDefault()
    setErrors([])
    save.mutate()
  }

  const checkError = check.error instanceof ApiError ? check.error.errors : check.error ? errorList(check.error) : []

  return (
    <form onSubmit={submit} className="space-y-5" noValidate>
      <div ref={errorRef}><ErrorBox errors={errors} /></div>

      <FormSection title="Ruta" description="Solo ida. Para ida y vuelta, crea también la vuelta y júntalas en un viaje.">
        <Field label="Nombre (opcional)">
          {(id) => <Input id={id} value={f.name} onChange={(e) => set('name', e.target.value)} placeholder="Sevilla → Tenerife" maxLength={200} />}
        </Field>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start">
          <PlaceCombobox key={`o${swaps}`} label="Origen" code={f.origin} place={f.originPlace} placeholder="Sevilla, SVQ…"
            onChange={(code, place) => setF((s) => ({ ...s, origin: code, originPlace: place }))} />
          <Button variant="ghost" size="icon" className="self-center sm:mt-7" aria-label="Intercambiar origen y destino"
            onClick={() => {
              setF((s) => ({ ...s, origin: s.destination, destination: s.origin, originPlace: s.destinationPlace,
                destinationPlace: s.originPlace }))
              setSwaps((n) => n + 1)
            }}>
            <ArrowLeftRight className="rotate-90 sm:rotate-0" />
          </Button>
          <PlaceCombobox key={`d${swaps}`} label="Destino" code={f.destination} place={f.destinationPlace} placeholder="Tenerife, TCI…"
            onChange={(code, place) => setF((s) => ({ ...s, destination: code, destinationPlace: place }))} />
        </div>
        <p className="text-xs text-muted">
          Una ciudad, un país o un grupo buscan en todos sus aeropuertos a la vez (p. ej. <code className="font-mono">TCI</code> =
          Tenerife Norte y Sur) y se quedan con el más barato de cada día. Como mucho {meta?.max_pairs ?? 60} combinaciones de aeropuertos.
        </p>
        <p className="text-xs text-muted">
          ¿Ida y vuelta? Crea las dos vigilancias y júntalas en un{' '}
          <Link to="/trips/new" className="text-accent underline underline-offset-2">viaje</Link>: te avisa por el precio total.
        </p>
      </FormSection>

      <FormSection
        title="Webs a vigilar"
        description={check.data ? `Comprobado para ${check.data.pairs.length === 1 ? 'la ruta' : `${check.data.pairs.length} combinaciones de aeropuertos`}.` : undefined}
      >
        <ErrorBox errors={checkError} />
        <div className="grid gap-2 sm:grid-cols-2" role="group" aria-label="Webs a vigilar" aria-busy={check.isFetching || undefined}>
          {meta?.providers.map((p) => (
            <ProviderOption key={p.key} p={p} checked={f.providers.includes(p.key)} result={check.isFetching ? undefined : results.get(p.key)}
              checking={check.isFetching} kept={kept.has(p.key)}
              onChange={(v) => {
                touched.current = true
                set('providers', toggle(f.providers, p.key, v))
              }} />
          ))}
        </div>
        {routeKey && (
          <Button variant="ghost" size="sm" onClick={() => check.refetch()} disabled={check.isFetching}>
            <RefreshCw /> Volver a comprobar
          </Button>
        )}
        <Field label="Escalas" hint="Las aerolíneas solo venden sus vuelos directos; con escalas solo busca Google Flights.">
          {(id, hint) => (
            <Select id={id} aria-describedby={hint} value={f.max_stops} onChange={(e) => set('max_stops', e.target.value)}
              className="sm:max-w-64">
              <option value="0">Solo directos</option>
              <option value="1">Hasta 1 escala</option>
              <option value="2">Hasta 2 escalas</option>
              <option value="">Sin límite</option>
            </Select>
          )}
        </Field>
      </FormSection>

      <FormSection title="Cuándo avisar" description="Basta con que se cumpla una de las dos reglas.">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Si cuesta como mucho (€)" hint="Déjalo vacío para usar solo la regla relativa.">
            {(id, hint) => <Input id={id} aria-describedby={hint} inputMode="decimal" value={f.max_price}
              onChange={(e) => set('max_price', e.target.value)} placeholder="40" />}
          </Field>
          <Field label="…o si baja un (%) sobre lo habitual"
            hint="Lo habitual es la mediana de los precios guardados de esa ruta y web (cuando hay suficientes).">
            {(id, hint) => <Input id={id} aria-describedby={hint} inputMode="decimal" value={f.discount_pct}
              onChange={(e) => set('discount_pct', e.target.value)} placeholder="30" />}
          </Field>
        </div>
      </FormSection>

      <FormSection title="Fechas de vuelo" description="Sin límites se comprueban todas las fechas con precio desde hoy.">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Desde (opcional)">
            {(id) => <Input id={id} type="date" value={f.date_from} onChange={(e) => set('date_from', e.target.value)} />}
          </Field>
          <Field label="Hasta (opcional)">
            {(id) => <Input id={id} type="date" value={f.date_to} min={f.date_from || undefined}
              onChange={(e) => set('date_to', e.target.value)} />}
          </Field>
        </div>
      </FormSection>

      <FormSection title="Canales de aviso" description="La vigilancia avisa solo a los canales marcados.">
        {channels.length ? (
          <div className="space-y-2.5" role="group" aria-label="Canales de aviso">
            {channels.map((c) => (
              <Checkbox key={c.id} checked={f.channel_ids.includes(c.id)} onChange={(v) => set('channel_ids', toggle(f.channel_ids, c.id, v))}>
                {c.name}
                <Badge tone={c.enabled ? 'accent' : 'neutral'}>{c.kind_label}{c.enabled ? '' : ' · pausado'}</Badge>
              </Checkbox>
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted">
            No tienes canales de aviso: esta vigilancia no avisará a nadie.{' '}
            <Link to="/profile/channels/new" className="text-accent underline underline-offset-2">Crea uno</Link>.
          </p>
        )}
      </FormSection>

      <div className="rounded-2xl border border-line bg-surface p-4 shadow-card sm:p-5">
        <Switch checked={f.enabled} onChange={(v) => set('enabled', v)} label="Vigilancia activa"
          description="En pausa no se comprueba en las rondas automáticas." />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" loading={save.isPending}>{isNew ? 'Crear vigilancia' : 'Guardar cambios'}</Button>
        <Link to={isNew ? '/' : `/watches/${watchId}`} className={buttonClass('ghost')}>Cancelar</Link>
        {!isNew && (
          <div className="ml-auto">
            <ConfirmDialog
              trigger={<Button variant="ghost" className="text-danger"><Trash2 /> Eliminar</Button>}
              title="¿Eliminar esta vigilancia?"
              description={`Se borrará también todo su histórico de precios, avisos y ejecuciones${trips.length
                ? `, y ${trips.length === 1 ? 'el viaje' : 'los viajes'} que la usa${trips.length === 1 ? '' : 'n'}: ${trips.map((t) => `«${t.name}»`).join(', ')}`
                : ''}. No se puede deshacer.`}
              onConfirm={() => remove.mutate()}
              loading={remove.isPending}
            />
          </div>
        )}
      </div>
    </form>
  )
}

const BLANK: FormState = {
  name: '', origin: '', destination: '', originPlace: null, destinationPlace: null, providers: [], max_price: '',
  discount_pct: '30', date_from: '', date_to: '', max_stops: '0', enabled: true, channel_ids: [],
}

/** Lugar por código (para precargar el formulario); null si no existe. */
const fetchPlace = (code: string) =>
  code ? get<{ place: Place }>(`/places/${encodeURIComponent(code)}`).then((r) => r.place, () => null) : Promise.resolve(null)

export function WatchFormPage() {
  const params = useParams()
  const [search] = useSearchParams()
  const id = params.id ? Number(params.id) : undefined
  const existing = useWatch(id ?? 0)
  // ?origin=…&destination=… precargan la ruta (p. ej. «Crear la vigilancia de vuelta» desde un viaje).
  const pre = { origin: search.get('origin') ?? '', destination: search.get('destination') ?? '' }
  const prefill = useQuery({
    queryKey: ['prefill', pre.origin, pre.destination],
    queryFn: async () => ({ origin: await fetchPlace(pre.origin), destination: await fetchPlace(pre.destination) }),
    enabled: id == null && !!(pre.origin || pre.destination),
    staleTime: Infinity,
  })
  useTitle(id ? 'Editar vigilancia' : 'Nueva vigilancia')

  if (id != null && existing.isPending) return <PageLoading />
  if (id != null && existing.isError) return <LoadError error={existing.error} />
  if (prefill.isLoading) return <PageLoading />
  const initial = id != null && existing.data ? fromWatch(existing.data.watch)
    : prefill.data ? {
      ...BLANK, origin: prefill.data.origin?.code ?? '', destination: prefill.data.destination?.code ?? '',
      originPlace: prefill.data.origin, destinationPlace: prefill.data.destination,
    } : BLANK

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader
        title={id ? 'Editar vigilancia' : 'Nueva vigilancia'}
        description={id ? existing.data?.watch.name : 'Elige la ruta, las webs y cuándo quieres que te avisemos.'}
      />
      <WatchForm key={id ?? 'new'} initial={initial} watchId={id} trips={existing.data?.trips} forTrip={search.get('for_trip')} />
    </div>
  )
}
