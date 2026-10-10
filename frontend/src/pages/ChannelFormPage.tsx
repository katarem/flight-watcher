import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'
import { toast } from 'sonner'
import { errorList, post, put } from '@/api/client'
import { keys, useChannel, useMe, useMeta, useUser } from '@/api/queries'
import type { ChannelDetail, ChannelField, ChannelFieldValue } from '@/api/types'
import { KindIcon } from '@/components/account/KindIcon'
import { Button, buttonClass } from '@/components/ui/button'
import { PageHeader } from '@/components/ui/card'
import { ErrorBox, LoadError, PageLoading } from '@/components/ui/feedback'
import { Field, FormSection, Input, Switch } from '@/components/ui/form'
import { useTitle } from '@/lib/hooks'

/** Rutas propias (/profile/channels…) o del admin sobre un usuario (/admin/users/{uid}/channels…). */
function useOwner() {
  const { uid } = useParams()
  const me = useMe().data!
  const userId = uid ? Number(uid) : null
  const user = useUser(userId)
  return {
    apiBase: userId != null ? `/users/${userId}` : '',
    back: userId != null ? `/admin/users/${userId}/edit` : '/profile',
    whose: userId != null && userId !== me.id && user.data ? ` · @${user.data.username}` : '',
  }
}

const KIND_HINTS: Record<string, string> = {
  discord: 'Un webhook de un canal de tu servidor.',
  telegram: 'Un bot que te escribe a ti o a un grupo.',
}

function KindPicker({ back }: { back: string }) {
  const meta = useMeta().data
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {meta?.channel_kinds.map((k) => (
        <Link key={k.key} to={`?kind=${k.key}`}
          className="group flex items-center gap-4 rounded-2xl border border-line bg-surface p-4 shadow-card transition hover:-translate-y-0.5 hover:border-accent">
          <KindIcon kind={k.key} />
          <div className="flex-1">
            <p className="font-semibold">{k.label}</p>
            {KIND_HINTS[k.key] && <p className="text-sm text-muted">{KIND_HINTS[k.key]}</p>}
          </div>
          <ChevronRight className="size-5 text-muted transition group-hover:translate-x-0.5" aria-hidden="true" />
        </Link>
      ))}
      <Link to={back} className={buttonClass('ghost', 'md', 'justify-self-start')}>Cancelar</Link>
    </div>
  )
}

function ChannelForm({ kind, kindLabel, fields, channel, apiBase, back }: {
  kind: string
  kindLabel: string
  fields: (ChannelField & Partial<ChannelFieldValue>)[]
  channel?: ChannelDetail
  apiBase: string
  back: string
}) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [name, setName] = useState(channel?.name ?? '')
  const [enabled, setEnabled] = useState(channel?.enabled ?? true)
  const [config, setConfig] = useState<Record<string, string>>(() =>
    Object.fromEntries(fields.map((f) => [f.key, f.secret ? '' : (f.value ?? '')])))
  const [errors, setErrors] = useState<string[]>([])

  const save = useMutation({
    mutationFn: () => {
      const body = { kind, name, enabled, config }
      return channel ? put(`${apiBase}/channels/${channel.id}`, body) : post(`${apiBase}/channels`, body)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['channels'] })
      qc.invalidateQueries({ queryKey: keys.watches })
      toast.success(channel ? `Canal «${name || kindLabel}» guardado` : `Canal «${name || kindLabel}» añadido`, {
        description: channel ? undefined : 'Asígnalo a tus vigilancias para recibir avisos.',
      })
      navigate(back)
    },
    onError: (e) => setErrors(errorList(e)),
  })

  const submit = (e: FormEvent) => {
    e.preventDefault()
    setErrors([])
    save.mutate()
  }

  return (
    <form onSubmit={submit} className="space-y-5" noValidate>
      <ErrorBox errors={errors} />
      <FormSection title={kindLabel}>
        <Field label="Nombre">
          {(id) => <Input id={id} value={name} onChange={(e) => setName(e.target.value)} maxLength={100} placeholder={kindLabel} />}
        </Field>
        {fields.map((f) => (
          <Field key={f.key} label={f.label} hint={f.saved ? 'Hay uno guardado: déjalo vacío para conservarlo.' : undefined}>
            {(id, hint) => (
              <Input id={id} aria-describedby={hint} value={config[f.key] ?? ''} autoComplete="off" spellCheck={false}
                type={f.secret ? 'password' : 'text'} placeholder={f.saved ? '•••••• guardado' : f.placeholder}
                onChange={(e) => setConfig((c) => ({ ...c, [f.key]: e.target.value }))} />
            )}
          </Field>
        ))}
        <Switch checked={enabled} onChange={setEnabled} label="Canal activo" description="Un canal en pausa no recibe avisos." />
      </FormSection>
      <div className="flex gap-2">
        <Button type="submit" loading={save.isPending}>{channel ? 'Guardar canal' : 'Añadir canal'}</Button>
        <Link to={back} className={buttonClass('ghost')}>Cancelar</Link>
      </div>
    </form>
  )
}

export function ChannelFormPage() {
  const { cid } = useParams()
  const [params] = useSearchParams()
  const owner = useOwner()
  const meta = useMeta()
  const channel = useChannel(owner.apiBase, cid ? Number(cid) : null)
  const isNew = !cid
  useTitle(isNew ? 'Nuevo canal' : 'Editar canal')

  if (meta.isPending || (!isNew && channel.isPending)) return <PageLoading />
  if (!isNew && channel.isError) return <LoadError error={channel.error} />
  const kind = isNew ? meta.data?.channel_kinds.find((k) => k.key === params.get('kind')) : undefined

  const backLink = (
    <Link to={owner.back} className="inline-flex items-center gap-1 text-sm text-muted hover:text-fg">
      <ChevronLeft className="size-4" aria-hidden="true" /> Volver
    </Link>
  )

  return (
    <div className="mx-auto max-w-2xl">
      {isNew && !kind ? (
        <>
          <PageHeader back={backLink} title={`Nuevo canal de aviso${owner.whose}`} description="¿Por dónde quieres recibir los avisos?" />
          <KindPicker back={owner.back} />
        </>
      ) : isNew && kind ? (
        <>
          <PageHeader back={backLink} title={`Nuevo canal de ${kind.label}${owner.whose}`} />
          <ChannelForm kind={kind.key} kindLabel={kind.label} fields={kind.fields} apiBase={owner.apiBase} back={owner.back} />
        </>
      ) : (
        <>
          <PageHeader back={backLink} title={`Editar canal de ${channel.data!.kind_label}${owner.whose}`} description={channel.data!.name} />
          <ChannelForm kind={channel.data!.kind} kindLabel={channel.data!.kind_label} fields={channel.data!.fields}
            channel={channel.data!} apiBase={owner.apiBase} back={owner.back} />
        </>
      )}
    </div>
  )
}
