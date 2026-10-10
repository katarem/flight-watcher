import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'
import { toast } from 'sonner'
import { del, errorList, post, put } from '@/api/client'
import { keys, useChannels, useTrip, useWatches } from '@/api/queries'
import type { Trip, WatchCard } from '@/api/types'
import { Button, buttonClass } from '@/components/ui/button'
import { Badge, PageHeader } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/dialog'
import { EmptyState, ErrorBox, LoadError, PageLoading } from '@/components/ui/feedback'
import { Checkbox, Field, FormSection, Input, Select, Switch } from '@/components/ui/form'
import { useTitle } from '@/lib/hooks'

interface FormState {
  name: string
  outbound_id: string
  return_id: string
  min_nights: string
  max_nights: string
  date_from: string
  date_to: string
  max_total: string
  discount_pct: string
  enabled: boolean
  channel_ids: number[]
}

const fromTrip = (t: Trip): FormState => ({
  name: t.name, outbound_id: String(t.outbound_id), return_id: String(t.return_id), min_nights: String(t.min_nights),
  max_nights: String(t.max_nights), date_from: t.date_from ?? '', date_to: t.date_to ?? '',
  max_total: t.max_total != null ? String(t.max_total) : '', discount_pct: String(Math.round(t.discount_pct)),
  enabled: t.enabled, channel_ids: t.channel_ids,
})

const toggle = <T,>(list: T[], v: T, on: boolean) => (on ? [...new Set([...list, v])] : list.filter((x) => x !== v))

const overlap = (a: string[], b: string[]) => a.some((x) => b.includes(x))

/** La vigilancia que hace el camino de vuelta de `w` (la ruta al revés), si la hay. */
const reverseOf = (w: WatchCard, all: WatchCard[]) =>
  all.find((x) => x.id !== w.id && x.origin === w.destination && x.destination === w.origin)

const watchLabel = (w: WatchCard) => `${w.name} (${w.origin} → ${w.destination})${w.enabled ? '' : ' · en pausa'}`

function TripForm({ initial, tripId, watches }: { initial: FormState; tripId?: number; watches: WatchCard[] }) {
  const isNew = tripId == null
  const channelData = useChannels('').data
  const channels = channelData ?? []
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [f, setF] = useState(initial)
  const [errors, setErrors] = useState<string[]>([])
  const errorRef = useRef<HTMLDivElement>(null)
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((s) => ({ ...s, [k]: v }))

  const out = watches.find((w) => String(w.id) === f.outbound_id)
  const ret = watches.find((w) => String(w.id) === f.return_id)
  const reverse = out && reverseOf(out, watches)
  const mismatch = out && ret && (
    !overlap(out.destination_place.airports, ret.origin_place.airports)
    || !overlap(ret.destination_place.airports, out.origin_place.airports))

  // Canales nuevos: por defecto, todos los activos (como en las vigilancias).
  const defaulted = useRef(!isNew)
  useEffect(() => {
    if (!defaulted.current && channelData?.length) {
      defaulted.current = true
      setF((s) => ({ ...s, channel_ids: channelData.filter((c) => c.enabled).map((c) => c.id) }))
    }
  }, [channelData])

  const pickOutbound = (id: string) => {
    const w = watches.find((x) => String(x.id) === id)
    const back = w && reverseOf(w, watches)
    // Si aún no hay vuelta elegida, se propone la ruta al revés.
    setF((s) => ({ ...s, outbound_id: id, return_id: s.return_id || (back ? String(back.id) : '') }))
  }

  const save = useMutation({
    mutationFn: () => {
      const body = { ...f, max_total: f.max_total || null, date_from: f.date_from || null, date_to: f.date_to || null }
      return isNew ? post<{ trip: Trip }>('/trips', body) : put<{ trip: Trip }>(`/trips/${tripId}`, body)
    },
    onSuccess: ({ trip }) => {
      qc.invalidateQueries({ queryKey: keys.trips })
      toast.success(isNew ? 'Viaje creado' : 'Cambios guardados')
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
      toast.success('Viaje eliminado (sus vigilancias se mantienen)')
      navigate('/trips')
    },
    onError: (e) => toast.error(errorList(e)[0]),
  })

  const submit = (e: FormEvent) => {
    e.preventDefault()
    setErrors([])
    save.mutate()
  }

  const newReturn = out && `/watches/new?origin=${encodeURIComponent(out.destination)}&destination=${encodeURIComponent(out.origin)}&for_trip=${out.id}`

  return (
    <form onSubmit={submit} className="space-y-5" noValidate>
      <div ref={errorRef}><ErrorBox errors={errors} /></div>

      <FormSection title="Ida y vuelta" description="Cada tramo es una de tus vigilancias: el viaje usa sus precios y sus webs.">
        <Field label="Nombre (opcional)">
          {(id) => <Input id={id} value={f.name} onChange={(e) => set('name', e.target.value)} placeholder="Tenerife en noviembre" maxLength={200} />}
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Vigilancia de ida">
            {(id) => (
              <Select id={id} value={f.outbound_id} onChange={(e) => pickOutbound(e.target.value)}>
                <option value="">Elige una…</option>
                {watches.map((w) => <option key={w.id} value={w.id}>{watchLabel(w)}</option>)}
              </Select>
            )}
          </Field>
          <Field label="Vigilancia de vuelta">
            {(id) => (
              <Select id={id} value={f.return_id} onChange={(e) => set('return_id', e.target.value)}>
                <option value="">Elige una…</option>
                {watches.map((w) => <option key={w.id} value={w.id}>{watchLabel(w)}</option>)}
              </Select>
            )}
          </Field>
        </div>
        {out && !reverse && (
          <p className="text-sm text-muted">
            No tienes ninguna vigilancia de {out.destination} a {out.origin}.{' '}
            <Link to={newReturn!} className="text-accent underline underline-offset-2">Crear la vigilancia de vuelta</Link>{' '}
            (después vuelves aquí con los dos tramos elegidos).
          </p>
        )}
        {mismatch && (
          <p className="rounded-xl border border-warn/30 bg-warn/10 p-3 text-sm text-warn">
            La vuelta no sale de donde llega la ida o no vuelve a donde sale: se puede guardar igualmente
            (p. ej. si vas en coche de un aeropuerto a otro).
          </p>
        )}
      </FormSection>

      <FormSection title="Noches y fechas" description="Se prueban todas las combinaciones de fecha de ida y noches.">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Noches como mínimo">
            {(id) => <Input id={id} inputMode="numeric" value={f.min_nights} onChange={(e) => set('min_nights', e.target.value)} placeholder="3" />}
          </Field>
          <Field label="Noches como máximo">
            {(id) => <Input id={id} inputMode="numeric" value={f.max_nights} onChange={(e) => set('max_nights', e.target.value)} placeholder="5" />}
          </Field>
          <Field label="Ida desde (opcional)">
            {(id) => <Input id={id} type="date" value={f.date_from} onChange={(e) => set('date_from', e.target.value)} />}
          </Field>
          <Field label="Ida hasta (opcional)">
            {(id) => <Input id={id} type="date" value={f.date_to} min={f.date_from || undefined}
              onChange={(e) => set('date_to', e.target.value)} />}
          </Field>
        </div>
      </FormSection>

      <FormSection title="Cuándo avisar" description="Sobre el total (ida + vuelta). Basta con que se cumpla una de las dos reglas.">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Si el total cuesta como mucho (€)" hint="Déjalo vacío para usar solo la regla relativa.">
            {(id, hint) => <Input id={id} aria-describedby={hint} inputMode="decimal" value={f.max_total}
              onChange={(e) => set('max_total', e.target.value)} placeholder="120" />}
          </Field>
          <Field label="…o si baja un (%) sobre lo habitual"
            hint="Lo habitual es la mediana de los totales guardados de este viaje (cuando hay suficientes).">
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
          description="En pausa no se recalcula en las rondas automáticas." />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" loading={save.isPending}>{isNew ? 'Crear viaje' : 'Guardar cambios'}</Button>
        <Link to={isNew ? '/trips' : `/trips/${tripId}`} className={buttonClass('ghost')}>Cancelar</Link>
        {!isNew && (
          <div className="ml-auto">
            <ConfirmDialog
              trigger={<Button variant="ghost" className="text-danger"><Trash2 /> Eliminar</Button>}
              title="¿Eliminar este viaje?"
              description="Se borrará su histórico de totales y avisos. Las vigilancias de ida y vuelta se mantienen."
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
  name: '', outbound_id: '', return_id: '', min_nights: '3', max_nights: '5', date_from: '', date_to: '',
  max_total: '', discount_pct: '30', enabled: true, channel_ids: [],
}

export function TripFormPage() {
  const params = useParams()
  const [search] = useSearchParams()
  const id = params.id ? Number(params.id) : undefined
  const existing = useTrip(id ?? 0)
  const watches = useWatches()
  useTitle(id ? 'Editar viaje' : 'Nuevo viaje')

  if ((id != null && existing.isPending) || watches.isPending) return <PageLoading />
  if (id != null && existing.isError) return <LoadError error={existing.error} />
  if (watches.isError) return <LoadError error={watches.error} />
  // Desde «Crear la vigilancia de vuelta» se vuelve con los dos tramos elegidos (?outbound=…&return=…).
  const initial = id != null && existing.data ? fromTrip(existing.data.trip)
    : { ...BLANK, outbound_id: search.get('outbound') ?? '', return_id: search.get('return') ?? '' }

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader
        title={id ? 'Editar viaje' : 'Nuevo viaje'}
        description={id ? existing.data?.trip.name : 'Elige la ida, la vuelta, cuántas noches y cuándo quieres que te avisemos.'}
      />
      {watches.data.length < 2 && id == null ? (
        <EmptyState
          icon={<Plus />}
          title="Hacen falta dos vigilancias"
          action={<Link to="/watches/new" className={buttonClass()}><Plus /> Nueva vigilancia</Link>}
        >
          Un viaje junta una vigilancia de ida y otra de vuelta. Crea primero las dos (p. ej. Sevilla → Tenerife y
          Tenerife → Sevilla).
        </EmptyState>
      ) : (
        <TripForm key={id ?? 'new'} initial={initial} tripId={id} watches={watches.data} />
      )}
    </div>
  )
}
