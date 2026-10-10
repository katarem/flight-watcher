import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeftRight, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { toast } from 'sonner'
import { del, errorList, post, put } from '@/api/client'
import { keys, useChannels, useMeta, useWatch } from '@/api/queries'
import type { Watch } from '@/api/types'
import { Button, buttonClass } from '@/components/ui/button'
import { Badge, PageHeader } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/dialog'
import { ErrorBox, LoadError, PageLoading } from '@/components/ui/feedback'
import { Checkbox, Field, FormSection, Input, Switch } from '@/components/ui/form'
import { cn } from '@/lib/cn'
import { useTitle } from '@/lib/hooks'

interface FormState {
  name: string
  origin: string
  destination: string
  providers: string[]
  max_price: string
  discount_pct: string
  date_from: string
  date_to: string
  enabled: boolean
  channel_ids: number[]
}

const fromWatch = (w: Watch): FormState => ({
  name: w.name, origin: w.origin, destination: w.destination, providers: w.providers,
  max_price: w.max_price != null ? String(w.max_price) : '', discount_pct: String(Math.round(w.discount_pct)),
  date_from: w.date_from ?? '', date_to: w.date_to ?? '', enabled: w.enabled, channel_ids: w.channel_ids,
})

const toggle = <T,>(list: T[], v: T, on: boolean) => (on ? [...new Set([...list, v])] : list.filter((x) => x !== v))

function WatchForm({ initial, watchId }: { initial: FormState; watchId?: number }) {
  const isNew = watchId == null
  const meta = useMeta().data
  const channelData = useChannels('').data
  const channels = channelData ?? []
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [f, setF] = useState(initial)
  const [errors, setErrors] = useState<string[]>([])
  const errorRef = useRef<HTMLDivElement>(null)
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((s) => ({ ...s, [k]: v }))

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
      const body = { ...f, max_price: f.max_price || null, date_from: f.date_from || null, date_to: f.date_to || null }
      return isNew ? post<{ watch: Watch }>('/watches', body) : put<{ watch: Watch }>(`/watches/${watchId}`, body)
    },
    onSuccess: ({ watch }) => {
      qc.invalidateQueries({ queryKey: keys.watches })
      toast.success(isNew ? 'Vigilancia creada' : 'Cambios guardados', {
        description: isNew ? 'Pulsa «Comprobar ahora» para traer los primeros precios.' : undefined,
      })
      navigate(`/watches/${watch.id}`)
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

  const iata = (k: 'origin' | 'destination', label: string, placeholder: string) => (
    <Field label={label} className="flex-1">
      {(id) => (
        <Input id={id} value={f[k]} onChange={(e) => set(k, e.target.value.toUpperCase().replace(/[^A-Z]/g, ''))}
          maxLength={3} required placeholder={placeholder} autoCapitalize="characters" autoComplete="off" spellCheck={false}
          className="font-mono text-base tracking-[0.2em] uppercase" pattern="[A-Za-z]{3}" />
      )}
    </Field>
  )

  return (
    <form onSubmit={submit} className="space-y-5" noValidate>
      <div ref={errorRef}><ErrorBox errors={errors} /></div>

      <FormSection title="Ruta" description="Solo ida. Para ida y vuelta, crea dos vigilancias.">
        <Field label="Nombre (opcional)">
          {(id) => <Input id={id} value={f.name} onChange={(e) => set('name', e.target.value)} placeholder="Sevilla → Tenerife" maxLength={200} />}
        </Field>
        <div className="flex items-end gap-2">
          {iata('origin', 'Origen (IATA)', 'SVQ')}
          <Button variant="ghost" size="icon" className="mb-0.5" aria-label="Intercambiar origen y destino"
            onClick={() => setF((s) => ({ ...s, origin: s.destination, destination: s.origin }))}>
            <ArrowLeftRight />
          </Button>
          {iata('destination', 'Destino (IATA)', 'TCI')}
        </div>
        <p className="text-xs text-muted">
          Admite códigos de ciudad: <code className="font-mono">TCI</code> busca a la vez en Tenerife Norte (TFN) y Tenerife Sur (TFS)
          y se queda con el más barato de cada día.
        </p>
      </FormSection>

      <FormSection title="Webs a vigilar">
        <div className="grid gap-2 sm:grid-cols-2" role="group" aria-label="Webs a vigilar">
          {meta?.providers.map((p) => {
            const on = f.providers.includes(p.key)
            return (
              <div key={p.key} className={cn('rounded-xl border p-3 transition', on ? 'border-accent bg-accent-soft/50' : 'border-line')}>
                <Checkbox checked={on} onChange={(v) => set('providers', toggle(f.providers, p.key, v))}>
                  <span aria-hidden="true" className="size-2.5 rounded-full" style={{ background: p.color }} />
                  {p.label}
                </Checkbox>
              </div>
            )
          })}
        </div>
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
              description="Se borrará también todo su histórico de precios, avisos y ejecuciones. No se puede deshacer."
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
  name: '', origin: '', destination: '', providers: ['vueling'], max_price: '', discount_pct: '30',
  date_from: '', date_to: '', enabled: true, channel_ids: [],
}

export function WatchFormPage() {
  const params = useParams()
  const id = params.id ? Number(params.id) : undefined
  const existing = useWatch(id ?? 0)
  useTitle(id ? 'Editar vigilancia' : 'Nueva vigilancia')

  if (id != null && existing.isPending) return <PageLoading />
  if (id != null && existing.isError) return <LoadError error={existing.error} />
  const initial = id != null && existing.data ? fromWatch(existing.data.watch) : BLANK

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader
        title={id ? 'Editar vigilancia' : 'Nueva vigilancia'}
        description={id ? existing.data?.watch.name : 'Elige la ruta, las webs y cuándo quieres que te avisemos.'}
      />
      <WatchForm key={id ?? 'new'} initial={initial} watchId={id} />
    </div>
  )
}
