import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, ArrowLeftRight, CheckCircle2, Clock, RefreshCw, Trash2, XCircle } from 'lucide-react'
import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { toast } from 'sonner'
import { ApiError, del, errorList, post, put } from '@/api/client'
import { keys, useChannels, useMeta, useTrip } from '@/api/queries'
import type { KindKey, Place, ProviderMeta, RouteCheck, RouteCheckProvider, Trip, TripLeg } from '@/api/types'
import { Button, buttonClass } from '@/components/ui/button'
import { Badge, PageHeader } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/dialog'
import { ErrorBox, LoadError, PageLoading, Spinner } from '@/components/ui/feedback'
import { Checkbox, Field, FormSection, Input, Select, Switch } from '@/components/ui/form'
import { PlaceCombobox } from '@/components/watch/PlaceCombobox'
import { cn } from '@/lib/cn'
import { useTitle } from '@/lib/hooks'
import { useKind } from '@/lib/kinds'

/** Estado de un tramo del viaje (una vigilancia interna). */
interface LegState {
  origin: string
  destination: string
  originPlace: Place | null
  destinationPlace: Place | null
  providers: string[]
  max_stops: string
}

interface FormState {
  name: string
  oneWay: boolean
  outbound: LegState
  ret: LegState
  min_nights: string
  max_nights: string
  date_from: string
  date_to: string
  max_total: string
  discount_pct: string
  enabled: boolean
  channel_ids: number[]
}

const BLANK_LEG: LegState = {
  origin: '', destination: '', originPlace: null, destinationPlace: null, providers: [], max_stops: '0',
}

const legFrom = (l: TripLeg): LegState => ({
  origin: l.origin, destination: l.destination, originPlace: l.origin_place, destinationPlace: l.destination_place,
  providers: l.providers, max_stops: l.max_stops == null ? '' : String(l.max_stops),
})

const fromTrip = (t: Trip): FormState => ({
  name: t.name, oneWay: !t.return, outbound: legFrom(t.outbound), ret: t.return ? legFrom(t.return) : { ...BLANK_LEG },
  min_nights: String(t.min_nights), max_nights: String(t.max_nights), date_from: t.date_from ?? '',
  date_to: t.date_to ?? '', max_total: t.max_total != null ? String(t.max_total) : '',
  discount_pct: String(Math.round(t.discount_pct)), enabled: t.enabled, channel_ids: t.channel_ids,
})

const BLANK: FormState = {
  name: '', oneWay: false, outbound: { ...BLANK_LEG }, ret: { ...BLANK_LEG }, min_nights: '3', max_nights: '7',
  date_from: '', date_to: '', max_total: '', discount_pct: '30', enabled: true, channel_ids: [],
}

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
          <><Spinner className="size-3.5 shrink-0" /> Comprobando si opera la ruta (algunas webs tardan un rato)…</>
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

/** Sub-formulario de un tramo: ruta, webs (con comprobación de la ruta) y escalas. */
function LegFields({ kind, leg, onChange, isNew, keptProviders }: {
  kind: KindKey
  leg: LegState
  onChange: (next: LegState) => void
  isNew: boolean
  keptProviders: string[]
}) {
  const meta = useMeta().data
  const k = useKind(kind)
  const providers = (meta?.providers ?? []).filter((p) => p.kind === kind)
  const [swaps, setSwaps] = useState(0)

  const routeKey = ready(leg.origin, leg.originPlace) && ready(leg.destination, leg.destinationPlace)
    ? `${leg.origin}|${leg.destination}` : ''
  const check = useQuery({
    queryKey: ['route-check', kind, routeKey],
    queryFn: () => post<RouteCheck>('/route-check', { kind, origin: leg.origin, destination: leg.destination }),
    enabled: !!routeKey,
    staleTime: 5 * 60_000,
    retry: false,
  })
  const results = new Map((check.data?.providers ?? []).map((r) => [r.key, r]))
  const kept = new Set(keptProviders)

  // Tramo nuevo: se marcan las webs que operan la ruta (hasta que el usuario toque las casillas).
  const touched = useRef(!isNew)
  const lastAuto = useRef('')
  useEffect(() => {
    const data = check.data
    if (!data || touched.current || lastAuto.current === routeKey) return
    lastAuto.current = routeKey
    onChange({ ...leg, providers: data.providers.filter((r) => r.ok && r.coverage !== 'universal').map((r) => r.key) })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [check.data, routeKey])

  const checkError = check.error instanceof ApiError ? check.error.errors : check.error ? errorList(check.error) : []

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start">
        <PlaceCombobox key={`o${swaps}`} kind={kind} label="Origen" code={leg.origin} place={leg.originPlace} placeholder="Sevilla, SVQ…"
          onChange={(code, place) => onChange({ ...leg, origin: code, originPlace: place })} />
        <Button variant="ghost" size="icon" className="self-center sm:mt-7" aria-label="Intercambiar origen y destino"
          onClick={() => {
            onChange({ ...leg, origin: leg.destination, destination: leg.origin, originPlace: leg.destinationPlace, destinationPlace: leg.originPlace })
            setSwaps((n) => n + 1)
          }}>
          <ArrowLeftRight className="rotate-90 sm:rotate-0" />
        </Button>
        <PlaceCombobox key={`d${swaps}`} kind={kind} label="Destino" code={leg.destination} place={leg.destinationPlace} placeholder="Tenerife, TCI…"
          onChange={(code, place) => onChange({ ...leg, destination: code, destinationPlace: place })} />
      </div>
      <ErrorBox errors={checkError} />
      <div className="grid gap-2 sm:grid-cols-2" role="group" aria-label="Webs a vigilar" aria-busy={check.isFetching || undefined}>
        {providers.map((p) => (
          <ProviderOption key={p.key} p={p} checked={leg.providers.includes(p.key)} result={check.isFetching ? undefined : results.get(p.key)}
            checking={check.isFetching} kept={kept.has(p.key)}
            onChange={(v) => { touched.current = true; onChange({ ...leg, providers: toggle(leg.providers, p.key, v) }) }} />
        ))}
      </div>
      {routeKey && (
        <Button variant="ghost" size="sm" onClick={() => check.refetch()} disabled={check.isFetching}>
          <RefreshCw /> Volver a comprobar
        </Button>
      )}
      <Field label="Escalas" hint={`La mayoría de las webs solo venden ${k.plural} directos; algunas también con escala.`}>
        {(id, hint) => (
          <Select id={id} aria-describedby={hint} value={leg.max_stops} onChange={(e) => onChange({ ...leg, max_stops: e.target.value })}
            className="sm:max-w-64">
            <option value="0">Solo directos</option>
            <option value="1">Hasta 1 escala</option>
            <option value="2">Hasta 2 escalas</option>
            <option value="">Sin límite</option>
          </Select>
        )}
      </Field>
    </div>
  )
}

function TripForm({ initial, tripId, kind, keptOut, keptRet }: {
  initial: FormState
  tripId?: number
  kind: KindKey
  keptOut: string[]
  keptRet: string[]
}) {
  const isNew = tripId == null
  const channelData = useChannels('').data
  const channels = channelData ?? []
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [f, setF] = useState(initial)
  const [errors, setErrors] = useState<string[]>([])
  const errorRef = useRef<HTMLDivElement>(null)
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((s) => ({ ...s, [k]: v }))

  // Canales nuevos: por defecto, todos los activos.
  const defaulted = useRef(!isNew)
  useEffect(() => {
    if (!defaulted.current && channelData?.length) {
      defaulted.current = true
      setF((s) => ({ ...s, channel_ids: channelData.filter((c) => c.enabled).map((c) => c.id) }))
    }
  }, [channelData])

  const legBody = (l: LegState) => ({
    kind, origin: l.origin, destination: l.destination, providers: l.providers, max_stops: l.max_stops,
  })

  const save = useMutation({
    mutationFn: () => {
      const body = {
        name: f.name, min_nights: f.min_nights, max_nights: f.max_nights, max_total: f.max_total || null,
        discount_pct: f.discount_pct, date_from: f.date_from || null, date_to: f.date_to || null,
        enabled: f.enabled, channel_ids: f.channel_ids,
        outbound: legBody(f.outbound), return: f.oneWay ? null : legBody(f.ret),
      }
      return isNew ? post<{ trip: Trip }>('/trips', body) : put<{ trip: Trip }>(`/trips/${tripId}`, body)
    },
    onSuccess: ({ trip }) => {
      qc.invalidateQueries({ queryKey: keys.trips })
      toast.success(isNew ? 'Viaje creado' : 'Cambios guardados', {
        description: isNew ? 'Pulsa «Comprobar ahora» para traer los primeros precios.' : undefined,
      })
      navigate(`/trips/${trip.id}`)
    },
    onError: (e) => {
      setErrors(errorList(e))
      requestAnimationFrame(() => errorRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' }))
    },
  })

  const remove = useMutation({
    mutationFn: () => del(`/trips/${tripId}`),
    onSuccess: () => {
      qc.removeQueries({ queryKey: keys.trip(tripId!) })
      qc.invalidateQueries({ queryKey: keys.trips })
      toast.success('Viaje eliminado junto con sus tramos y su histórico')
      navigate('/trips')
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
      <div ref={errorRef}><ErrorBox errors={errors} /></div>

      <FormSection title="El viaje" description="Un nombre y si es ida y vuelta o solo ida.">
        <Field label="Nombre (opcional)">
          {(id) => <Input id={id} value={f.name} onChange={(e) => set('name', e.target.value)} placeholder="Tenerife en noviembre" maxLength={200} />}
        </Field>
        <Checkbox checked={f.oneWay} onChange={(v) => set('oneWay', v)}>Solo ida (sin vuelta)</Checkbox>
      </FormSection>

      <FormSection title="Tramo de ida" description="La ruta, las webs y las escalas de la ida. El viaje usa sus precios.">
        <LegFields kind={kind} leg={f.outbound} onChange={(l) => set('outbound', l)} isNew={isNew} keptProviders={keptOut} />
      </FormSection>

      {!f.oneWay && (
        <FormSection title="Tramo de vuelta" description="La ruta de vuelta (normalmente al revés que la ida).">
          <LegFields kind={kind} leg={f.ret} onChange={(l) => set('ret', l)} isNew={isNew} keptProviders={keptRet} />
        </FormSection>
      )}

      {!f.oneWay && (
        <FormSection title="Noches y fechas" description="Se prueban todas las combinaciones de fecha de ida y noches.">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Noches como mínimo">
              {(id) => <Input id={id} inputMode="numeric" value={f.min_nights} onChange={(e) => set('min_nights', e.target.value)} placeholder="3" />}
            </Field>
            <Field label="Noches como máximo">
              {(id) => <Input id={id} inputMode="numeric" value={f.max_nights} onChange={(e) => set('max_nights', e.target.value)} placeholder="7" />}
            </Field>
          </div>
        </FormSection>
      )}

      <FormSection title="Fechas de ida" description="Sin límites se comprueban todas las fechas con precio desde hoy.">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Ida desde (opcional)">
            {(id) => <Input id={id} type="date" value={f.date_from} onChange={(e) => set('date_from', e.target.value)} />}
          </Field>
          <Field label="Ida hasta (opcional)">
            {(id) => <Input id={id} type="date" value={f.date_to} min={f.date_from || undefined}
              onChange={(e) => set('date_to', e.target.value)} />}
          </Field>
        </div>
      </FormSection>

      <FormSection title="Cuándo avisar"
        description={`Sobre ${f.oneWay ? 'el precio de la ida' : 'el total (ida + vuelta)'}. Basta con que se cumpla una de las dos reglas.`}>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={`Si ${f.oneWay ? 'cuesta' : 'el total cuesta'} como mucho (€)`} hint="Déjalo vacío para usar solo la regla relativa.">
            {(id, hint) => <Input id={id} aria-describedby={hint} inputMode="decimal" value={f.max_total}
              onChange={(e) => set('max_total', e.target.value)} placeholder="120" />}
          </Field>
          <Field label="…o si baja un (%) sobre lo habitual"
            hint="Lo habitual es la mediana de los precios guardados de este viaje (cuando hay suficientes).">
            {(id, hint) => <Input id={id} aria-describedby={hint} inputMode="decimal" value={f.discount_pct}
              onChange={(e) => set('discount_pct', e.target.value)} placeholder="30" />}
          </Field>
        </div>
      </FormSection>

      <FormSection title="Canales de aviso" description="El viaje avisa solo a los canales marcados (de las 5 fechas de ida más baratas, una vez cada una).">
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
            No tienes canales de aviso: este viaje no avisará a nadie.{' '}
            <Link to="/profile/channels/new" className="text-accent underline underline-offset-2">Crea uno</Link>.
          </p>
        )}
      </FormSection>

      <div className="rounded-2xl border border-line bg-surface p-4 shadow-card sm:p-5">
        <Switch checked={f.enabled} onChange={(v) => set('enabled', v)} label="Viaje activo"
          description="En pausa no se comprueba en las rondas automáticas." />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" loading={save.isPending}>{isNew ? 'Crear viaje' : 'Guardar cambios'}</Button>
        <Link to={isNew ? '/trips' : `/trips/${tripId}`} className={buttonClass('ghost')}>Cancelar</Link>
        {!isNew && (
          <div className="ml-auto">
            <ConfirmDialog
              trigger={<Button variant="ghost" className="text-danger"><Trash2 /> Eliminar</Button>}
              title="¿Eliminar este viaje?"
              description="Se borrarán sus tramos y todo su histórico de precios, avisos y ejecuciones. No se puede deshacer."
              onConfirm={() => remove.mutate()}
              loading={remove.isPending}
            />
          </div>
        )}
      </div>
    </form>
  )
}

export function TripFormPage() {
  const params = useParams()
  const id = params.id ? Number(params.id) : undefined
  const existing = useTrip(id ?? 0)
  useTitle(id ? 'Editar viaje' : 'Nuevo viaje')

  if (id != null && existing.isPending) return <PageLoading />
  if (id != null && existing.isError) return <LoadError error={existing.error} />
  const trip = id != null ? existing.data?.trip : undefined
  const initial = trip ? fromTrip(trip) : BLANK
  const kind = trip?.kind ?? 'flight'
  // Al editar, los proveedores de temporada (inactivos) de cada tramo se conservan aunque la ruta no los opere.
  const keptOut = trip ? trip.outbound.providers : []
  const keptRet = trip?.return ? trip.return.providers : []

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader
        title={id ? 'Editar viaje' : 'Nuevo viaje'}
        description={id ? trip?.name : 'Elige la ruta de la ida (y la vuelta), las webs y cuándo quieres que te avisemos.'}
      />
      <TripForm key={id ?? 'new'} initial={initial} tripId={id} kind={kind} keptOut={keptOut} keptRet={keptRet} />
    </div>
  )
}
