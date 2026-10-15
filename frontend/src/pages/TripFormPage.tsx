import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, ArrowLeftRight, CheckCircle2, Clock, Plus, RefreshCw, Repeat, Trash2, X, XCircle } from 'lucide-react'
import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'
import { toast } from 'sonner'
import { ApiError, del, errorList, get, post, put } from '@/api/client'
import { keys, useChannels, useMeta, useTrip } from '@/api/queries'
import type { KindKey, Option, Place, ProviderMeta, RouteCheck, RouteCheckProvider, Trip, TripLeg, TripStay } from '@/api/types'
import { Button, buttonClass } from '@/components/ui/button'
import { Badge, PageHeader } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/dialog'
import { ErrorBox, LoadError, PageLoading, Spinner } from '@/components/ui/feedback'
import { Checkbox, Field, FormSection, Input, Select, Switch } from '@/components/ui/form'
import { PlaceCombobox } from '@/components/watch/PlaceCombobox'
import { cn } from '@/lib/cn'
import { useTitle } from '@/lib/hooks'
import { tripPath } from '@/lib/paths'
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

/** Estado de la estancia (alojamiento) del viaje: destino en texto, webs y filtros. */
interface StayState {
  destination: string
  providers: string[]
  rooms: string
  types: string[]
  entire: boolean
  min_rating: string
  min_stars: string
  boards: string[]
  free_cancel: boolean
  amenities: string[]
}

/** Un viajero: edad ('' = adulto) y residencia ('' = sin descuento). */
interface TravelerState {
  age: string
  resident: string
}

interface FormState {
  name: string
  /** Vigila el transporte (ida y, si no es solo ida, vuelta). */
  transport: boolean
  oneWay: boolean
  outbound: LegState
  ret: LegState
  /** Vigila el alojamiento. */
  withStay: boolean
  stay: StayState
  travelers: TravelerState[]
  large_family: string
  min_nights: string
  max_nights: string
  date_from: string
  date_to: string
  max_total: string
  max_per_person: string
  discount_pct: string
  enabled: boolean
  channel_ids: number[]
}

const BLANK_LEG: LegState = {
  origin: '', destination: '', originPlace: null, destinationPlace: null, providers: [], max_stops: '0',
}

const BLANK_STAY: StayState = {
  destination: '', providers: [], rooms: '1', types: [], entire: false, min_rating: '', min_stars: '', boards: [],
  free_cancel: false, amenities: [],
}

const stayFrom = (st: TripStay): StayState => ({
  destination: st.destination, providers: st.providers, rooms: String(st.filters.rooms), types: st.filters.types,
  entire: st.filters.entire, min_rating: st.filters.min_rating != null ? String(st.filters.min_rating) : '',
  min_stars: st.filters.min_stars != null ? String(st.filters.min_stars) : '', boards: st.filters.boards,
  free_cancel: st.filters.free_cancel, amenities: st.filters.amenities,
})

const legFrom = (l: TripLeg): LegState => ({
  origin: l.origin, destination: l.destination, originPlace: l.origin_place, destinationPlace: l.destination_place,
  providers: l.providers, max_stops: l.max_stops == null ? '' : String(l.max_stops),
})

const fromTrip = (t: Trip): FormState => ({
  name: t.name, transport: !!t.outbound, oneWay: !t.return,
  outbound: t.outbound ? legFrom(t.outbound) : { ...BLANK_LEG }, ret: t.return ? legFrom(t.return) : { ...BLANK_LEG },
  withStay: !!t.stay, stay: t.stay ? stayFrom(t.stay) : { ...BLANK_STAY },
  travelers: t.party.travelers.map((x) => ({ age: x.age == null ? '' : String(x.age), resident: x.resident })),
  large_family: t.party.large_family,
  min_nights: String(t.min_nights), max_nights: String(t.max_nights), date_from: t.date_from ?? '',
  date_to: t.date_to ?? '', max_total: t.max_total != null ? String(t.max_total) : '',
  max_per_person: t.max_per_person != null ? String(t.max_per_person) : '',
  discount_pct: String(Math.round(t.discount_pct)), enabled: t.enabled, channel_ids: t.channel_ids,
})

const BLANK: FormState = {
  name: '', transport: true, oneWay: false, outbound: { ...BLANK_LEG }, ret: { ...BLANK_LEG }, withStay: false,
  stay: { ...BLANK_STAY }, travelers: [{ age: '', resident: '' }], large_family: '', min_nights: '3', max_nights: '7',
  date_from: '', date_to: '', max_total: '', max_per_person: '', discount_pct: '30', enabled: true, channel_ids: [],
}

/** La vuelta de un tramo: la misma ruta al revés, con las mismas webs y escalas. */
const reversed = (l: LegState): LegState => ({
  ...l, origin: l.destination, destination: l.origin, originPlace: l.destinationPlace, destinationPlace: l.originPlace,
})

/** Lugar por código (para precargar el formulario); null si no existe. */
const fetchPlace = (code: string) =>
  code ? get<{ place: Place }>(`/places/${encodeURIComponent(code)}`).then((r) => r.place, () => null) : Promise.resolve(null)

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

/** Sub-formulario de un tramo: ruta, webs (con comprobación de la ruta) y escalas. `of` («de la ida») distingue los
 *  campos de cada tramo. */
function LegFields({ of, kind, leg, onChange, isNew, keptProviders }: {
  of: string
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
        <PlaceCombobox key={`o${swaps}`} kind={kind} label={`Origen ${of}`} code={leg.origin} place={leg.originPlace} placeholder="Sevilla, SVQ…"
          onChange={(code, place) => onChange({ ...leg, origin: code, originPlace: place })} />
        <Button variant="ghost" size="icon" className="self-center sm:mt-7" aria-label={`Intercambiar origen y destino ${of}`}
          onClick={() => {
            onChange({ ...leg, origin: leg.destination, destination: leg.origin, originPlace: leg.destinationPlace, destinationPlace: leg.originPlace })
            setSwaps((n) => n + 1)
          }}>
          <ArrowLeftRight className="rotate-90 sm:rotate-0" />
        </Button>
        <PlaceCombobox key={`d${swaps}`} kind={kind} label={`Destino ${of}`} code={leg.destination} place={leg.destinationPlace} placeholder="Tenerife, TCI…"
          onChange={(code, place) => onChange({ ...leg, destination: code, destinationPlace: place })} />
      </div>
      <ErrorBox errors={checkError} />
      <div className="grid gap-2 sm:grid-cols-2" role="group" aria-label={`Webs ${of}`} aria-busy={check.isFetching || undefined}>
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
      <Field label={`Escalas ${of}`} hint={`La mayoría de las webs solo venden ${k.plural} directos; algunas también con escala.`}>
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

/** Un grupo de casillas (tipos de alojamiento, regímenes, servicios) con nombre para los lectores de pantalla. */
function CheckGroup({ label, hint, options, value, onChange }: {
  label: string
  hint?: string
  options: Option[]
  value: string[]
  onChange: (next: string[]) => void
}) {
  const id = useId()
  return (
    <div role="group" aria-labelledby={id} aria-describedby={hint ? `${id}-hint` : undefined} className="space-y-2">
      <p id={id} className="text-sm font-medium">{label}</p>
      {hint && <p id={`${id}-hint`} className="text-xs text-muted">{hint}</p>}
      <div className="flex flex-wrap gap-x-5 gap-y-2">
        {options.map((o) => (
          <Checkbox key={o.key} checked={value.includes(o.key)} onChange={(v) => onChange(toggle(value, o.key, v))}>{o.label}</Checkbox>
        ))}
      </div>
    </div>
  )
}

/** Sub-formulario de la estancia: destino (texto libre), webs de alojamiento y filtros. */
function StayFields({ stay, onChange, isNew }: { stay: StayState; onChange: (next: StayState) => void; isNew: boolean }) {
  const meta = useMeta().data
  const options = meta?.stay_options
  const providers = (meta?.providers ?? []).filter((p) => p.kind === 'hotel')
  const set = <K extends keyof StayState>(k: K, v: StayState[K]) => onChange({ ...stay, [k]: v })

  // Estancia nueva: todas las webs de alojamiento marcadas (no hay rutas que comprobar).
  const defaulted = useRef(!isNew || stay.providers.length > 0)
  useEffect(() => {
    if (!defaulted.current && providers.length) {
      defaulted.current = true
      onChange({ ...stay, providers: providers.map((p) => p.key) })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [providers.length])

  return (
    <div className="space-y-4">
      <Field label="Destino del alojamiento" hint="Una ciudad, una isla o una zona («Puerto de la Cruz», «Costa Adeje»): lo busca cada web.">
        {(id, hint) => <Input id={id} aria-describedby={hint} value={stay.destination} maxLength={options?.place_max ?? 120}
          onChange={(e) => set('destination', e.target.value)} placeholder="Puerto de la Cruz" />}
      </Field>
      {providers.length ? (
        <div className="grid gap-2 sm:grid-cols-2" role="group" aria-label="Webs del alojamiento">
          {providers.map((p) => (
            <div key={p.key} className={cn('rounded-xl border p-3 transition', stay.providers.includes(p.key) ? 'border-accent bg-accent-soft/50' : 'border-line')}>
              <Checkbox checked={stay.providers.includes(p.key)} onChange={(v) => set('providers', toggle(stay.providers, p.key, v))}>
                <span aria-hidden="true" className="size-2.5 rounded-full" style={{ background: p.color }} />
                {p.label}
              </Checkbox>
            </div>
          ))}
        </div>
      ) : (
        <p className="rounded-xl border border-warn/30 bg-warn/10 p-3 text-sm text-warn">
          Todavía no hay webs de alojamiento. Un administrador puede añadirlas en Proveedores (tipo «Alojamiento»).
        </p>
      )}
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Habitaciones">
          {(id) => <Input id={id} inputMode="numeric" value={stay.rooms} onChange={(e) => set('rooms', e.target.value)} placeholder="1" />}
        </Field>
        <Field label="Puntuación mínima">
          {(id) => (
            <Select id={id} value={stay.min_rating} onChange={(e) => set('min_rating', e.target.value)}>
              <option value="">Cualquiera</option>
              {['6', '7', '8', '9'].map((n) => <option key={n} value={n}>{n} o más (sobre 10)</option>)}
            </Select>
          )}
        </Field>
        <Field label="Estrellas mínimas">
          {(id) => (
            <Select id={id} value={stay.min_stars} onChange={(e) => set('min_stars', e.target.value)}>
              <option value="">Cualquiera</option>
              {['1', '2', '3', '4', '5'].map((n) => <option key={n} value={n}>{n} o más</option>)}
            </Select>
          )}
        </Field>
      </div>
      <CheckGroup label="Tipos de alojamiento" hint="Sin marcar ninguno, cualquiera. Desmarca los que no quieras (p. ej. hostales)."
        options={options?.types ?? []} value={stay.types} onChange={(v) => set('types', v)} />
      <CheckGroup label="Régimen" hint="Sin marcar ninguno, cualquiera." options={options?.boards ?? []} value={stay.boards}
        onChange={(v) => set('boards', v)} />
      <CheckGroup label="Servicios imprescindibles" options={options?.amenities ?? []} value={stay.amenities}
        onChange={(v) => set('amenities', v)} />
      <div className="flex flex-wrap gap-x-6 gap-y-2.5">
        <Checkbox checked={stay.entire} onChange={(v) => set('entire', v)}>Solo alojamientos enteros (nada de habitaciones compartidas)</Checkbox>
        <Checkbox checked={stay.free_cancel} onChange={(v) => set('free_cancel', v)}>Con cancelación gratuita</Checkbox>
      </div>
    </div>
  )
}

/** Los viajeros del viaje: edad (o adulto) y residencia de cada uno, y familia numerosa. */
function TravelersFields({ travelers, largeFamily, onChange, onLargeFamily }: {
  travelers: TravelerState[]
  largeFamily: string
  onChange: (next: TravelerState[]) => void
  onLargeFamily: (v: string) => void
}) {
  const options = useMeta().data?.party_options
  const max = options?.max_travelers ?? 9
  const ages = Array.from({ length: options?.adult_age ?? 18 }, (_, n) => n)
  const update = (i: number, patch: Partial<TravelerState>) => onChange(travelers.map((t, j) => (j === i ? { ...t, ...patch } : t)))
  return (
    <div className="space-y-3">
      <ul className="space-y-3">
        {travelers.map((t, i) => (
          <li key={i} className="grid items-end gap-2 sm:grid-cols-[1fr_1fr_auto]">
            <Field label={`Viajero ${i + 1}: edad`}>
              {(id) => (
                <Select id={id} value={t.age} onChange={(e) => update(i, { age: e.target.value })}>
                  <option value="">Adulto</option>
                  {ages.map((n) => <option key={n} value={String(n)}>{n === 0 ? 'Bebé (menos de 1 año)' : `${n} ${n === 1 ? 'año' : 'años'}`}</option>)}
                </Select>
              )}
            </Field>
            <Field label={`Viajero ${i + 1}: residencia`}>
              {(id) => (
                <Select id={id} value={t.resident} onChange={(e) => update(i, { resident: e.target.value })}>
                  <option value="">Sin descuento de residente</option>
                  {(options?.regions ?? []).map((r) => <option key={r.key} value={r.key}>Residente en {r.label}</option>)}
                </Select>
              )}
            </Field>
            <Button variant="ghost" size="icon" aria-label={`Quitar el viajero ${i + 1}`} disabled={travelers.length === 1}
              onClick={() => onChange(travelers.filter((_, j) => j !== i))}>
              <X />
            </Button>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap items-end gap-3">
        <Button variant="secondary" size="sm" disabled={travelers.length >= max}
          onClick={() => onChange([...travelers, { age: '', resident: '' }])}>
          <Plus /> Añadir viajero
        </Button>
        <Field label="Familia numerosa" className="w-full sm:w-56">
          {(id) => (
            <Select id={id} value={largeFamily} onChange={(e) => onLargeFamily(e.target.value)}>
              {(options?.large_family ?? [{ key: '', label: 'No' }]).map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
            </Select>
          )}
        </Field>
      </div>
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
  // Al rellenar la vuelta desde fuera, sus campos se vuelven a montar (los lugares toman su texto al montarse).
  const [retKey, setRetKey] = useState(0)
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

  const stayBody = (st: StayState) => ({
    destination: st.destination, providers: st.providers,
    filters: {
      rooms: st.rooms, types: st.types, entire: st.entire, min_rating: st.min_rating || null,
      min_stars: st.min_stars || null, boards: st.boards, free_cancel: st.free_cancel, amenities: st.amenities,
    },
  })

  const save = useMutation({
    mutationFn: () => {
      const body = {
        name: f.name, min_nights: f.min_nights, max_nights: f.max_nights, max_total: f.max_total || null,
        max_per_person: f.max_per_person || null,
        discount_pct: f.discount_pct, date_from: f.date_from || null, date_to: f.date_to || null,
        enabled: f.enabled, channel_ids: f.channel_ids,
        outbound: f.transport ? legBody(f.outbound) : null, return: f.transport && !f.oneWay ? legBody(f.ret) : null,
        stay: f.withStay ? stayBody(f.stay) : null,
        party: {
          travelers: f.travelers.map((t) => ({ age: t.age === '' ? null : t.age, resident: t.resident })),
          large_family: f.large_family,
        },
      }
      return isNew ? post<{ trip: Trip }>('/trips', body) : put<{ trip: Trip }>(`/trips/${tripId}`, body)
    },
    onSuccess: ({ trip }) => {
      qc.invalidateQueries({ queryKey: keys.trips })
      toast.success(isNew ? 'Viaje creado' : 'Cambios guardados', {
        description: isNew ? 'Pulsa «Comprobar ahora» para traer los primeros precios.' : undefined,
      })
      navigate(tripPath(trip.id))
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

  const nights = (f.transport && !f.oneWay) || f.withStay
  const day = f.transport ? 'ida' : 'entrada'
  const many = f.travelers.length > 1
  const parts = [f.transport && 'ida', f.transport && !f.oneWay && 'vuelta', f.withStay && 'alojamiento'].filter(Boolean)
  const totalOf = parts.length > 1 ? `el total (${parts.join(' + ')})` : `el precio ${f.transport ? 'de la ida' : 'del alojamiento'}`

  const submit = (e: FormEvent) => {
    e.preventDefault()
    setErrors([])
    save.mutate()
  }

  return (
    <form onSubmit={submit} className="space-y-5" noValidate>
      <div ref={errorRef}><ErrorBox errors={errors} /></div>

      <FormSection title="El viaje" description="Un nombre y qué vigila: el transporte, el alojamiento o los dos.">
        <Field label="Nombre (opcional)">
          {(id) => <Input id={id} value={f.name} onChange={(e) => set('name', e.target.value)} placeholder="Tenerife en noviembre" maxLength={200} />}
        </Field>
        <div role="group" aria-label="Qué vigila el viaje" className="flex flex-wrap gap-x-6 gap-y-2.5">
          <Checkbox checked={f.transport} onChange={(v) => set('transport', v)}>Transporte</Checkbox>
          <Checkbox checked={f.withStay} onChange={(v) => set('withStay', v)}>Alojamiento</Checkbox>
          {f.transport && <Checkbox checked={f.oneWay} onChange={(v) => set('oneWay', v)}>Solo ida (sin vuelta)</Checkbox>}
        </div>
        {!f.transport && !f.withStay && (
          <p className="text-sm text-warn">Marca el transporte, el alojamiento o los dos.</p>
        )}
      </FormSection>

      <FormSection title="Viajeros"
        description="Cambian el precio: los transportes se buscan para todos (con sus descuentos si la web los admite) y el alojamiento, para el grupo.">
        <TravelersFields travelers={f.travelers} largeFamily={f.large_family} onChange={(v) => set('travelers', v)}
          onLargeFamily={(v) => set('large_family', v)} />
      </FormSection>

      {f.transport && (
        <FormSection title="Tramo de ida" description="La ruta, las webs y las escalas de la ida. El viaje usa sus precios.">
          <LegFields of="de la ida" kind={kind} leg={f.outbound} onChange={(l) => set('outbound', l)} isNew={isNew} keptProviders={keptOut} />
        </FormSection>
      )}

      {f.transport && !f.oneWay && (
        <FormSection title="Tramo de vuelta" description="La ruta de vuelta (normalmente al revés que la ida).">
          {f.outbound.origin && f.outbound.destination && (
            <Button variant="secondary" size="sm" onClick={() => {
              set('ret', reversed(f.outbound))
              setRetKey((n) => n + 1)
            }}>
              <Repeat /> Al revés que la ida
            </Button>
          )}
          <LegFields key={retKey} of="de la vuelta" kind={kind} leg={f.ret} onChange={(l) => set('ret', l)} isNew={isNew} keptProviders={keptRet} />
        </FormSection>
      )}

      {f.withStay && (
        <FormSection title="Alojamiento"
          description={f.transport ? 'Se busca para las fechas de ida más baratas, con entrada el día de la ida.' : 'Se busca para cada fecha de entrada y número de noches.'}>
          <StayFields stay={f.stay} onChange={(v) => set('stay', v)} isNew={isNew || !initial.withStay} />
        </FormSection>
      )}

      {nights && (
        <FormSection title="Noches" description={`Se prueban todas las combinaciones de fecha de ${day} y noches.`}>
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

      <FormSection title={`Fechas de ${day}`}
        description={f.transport ? 'Sin límites se comprueban todas las fechas con precio desde hoy.'
          : 'Sin «hasta» se buscan las entradas de los próximos dos meses. Cuanto más acotes, antes se cubren todas.'}>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={`${f.transport ? 'Ida' : 'Entrada'} desde (opcional)`}>
            {(id) => <Input id={id} type="date" value={f.date_from} onChange={(e) => set('date_from', e.target.value)} />}
          </Field>
          <Field label={`${f.transport ? 'Ida' : 'Entrada'} hasta (opcional)`}>
            {(id) => <Input id={id} type="date" value={f.date_to} min={f.date_from || undefined}
              onChange={(e) => set('date_to', e.target.value)} />}
          </Field>
        </div>
      </FormSection>

      <FormSection title="Cuándo avisar"
        description={`Sobre ${totalOf}${many ? ', para todos los viajeros' : ''}. Basta con que se cumpla una de las reglas.`}>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={`Si ${parts.length > 1 ? 'el total cuesta' : 'cuesta'} como mucho (€)`} hint="Déjalo vacío para usar solo las demás reglas.">
            {(id, hint) => <Input id={id} aria-describedby={hint} inputMode="decimal" value={f.max_total}
              onChange={(e) => set('max_total', e.target.value)} placeholder="120" />}
          </Field>
          <Field label="…o si sale como mucho por persona (€)" hint="El total entre los viajeros: útil si cambia el grupo.">
            {(id, hint) => <Input id={id} aria-describedby={hint} inputMode="decimal" value={f.max_per_person}
              onChange={(e) => set('max_per_person', e.target.value)} placeholder="60" />}
          </Field>
          <Field label="…o si baja un (%) sobre lo habitual"
            hint="Lo habitual es la mediana de los precios guardados de este viaje (cuando hay suficientes).">
            {(id, hint) => <Input id={id} aria-describedby={hint} inputMode="decimal" value={f.discount_pct}
              onChange={(e) => set('discount_pct', e.target.value)} placeholder="30" />}
          </Field>
        </div>
      </FormSection>

      <FormSection title="Canales de aviso" description={`El viaje avisa solo a los canales marcados (de las 5 fechas de ${day} más baratas, una vez cada una).`}>
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
        <Link to={isNew ? '/trips' : tripPath(tripId)} className={buttonClass('ghost')}>Cancelar</Link>
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
  const [search] = useSearchParams()
  const id = params.id ? Number(params.id) : undefined
  const existing = useTrip(id ?? 0)
  // ?origin=…&destination=… precargan la ida y, al revés, la vuelta (p. ej. desde las URL de antes de la 2.0).
  const pre = { origin: search.get('origin') ?? '', destination: search.get('destination') ?? '' }
  const prefill = useQuery({
    queryKey: ['prefill', pre.origin, pre.destination],
    queryFn: async () => ({ origin: await fetchPlace(pre.origin), destination: await fetchPlace(pre.destination) }),
    enabled: id == null && !!(pre.origin || pre.destination),
    staleTime: Infinity,
  })
  useTitle(id ? 'Editar viaje' : 'Nuevo viaje')

  if (id != null && existing.isPending) return <PageLoading />
  if (id != null && existing.isError) return <LoadError error={existing.error} />
  if (prefill.isLoading) return <PageLoading />
  const trip = id != null ? existing.data?.trip : undefined
  const preOut: LegState | null = prefill.data ? {
    ...BLANK_LEG, origin: prefill.data.origin?.code ?? '', destination: prefill.data.destination?.code ?? '',
    originPlace: prefill.data.origin, destinationPlace: prefill.data.destination,
  } : null
  const initial = trip ? fromTrip(trip) : preOut ? { ...BLANK, outbound: preOut, ret: reversed(preOut) } : BLANK
  const kind = trip?.outbound?.kind ?? 'flight'
  // Al editar, los proveedores de temporada (inactivos) de cada tramo se conservan aunque la ruta no los opere.
  const keptOut = trip?.outbound ? trip.outbound.providers : []
  const keptRet = trip?.return ? trip.return.providers : []

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader
        title={id ? 'Editar viaje' : 'Nuevo viaje'}
        description={id ? trip?.name : 'Elige el transporte (ida y vuelta), el alojamiento o los dos, los viajeros y cuándo quieres que te avisemos.'}
      />
      <TripForm key={id ?? 'new'} initial={initial} tripId={id} kind={kind} keptOut={keptOut} keptRet={keptRet} />
    </div>
  )
}
