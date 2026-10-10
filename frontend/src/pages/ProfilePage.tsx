import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { toast } from 'sonner'
import { errorList, post, put } from '@/api/client'
import { keys, useMe } from '@/api/queries'
import type { Me, User } from '@/api/types'
import { AvatarUploader } from '@/components/account/AvatarUploader'
import { ChannelList } from '@/components/account/ChannelList'
import { Button } from '@/components/ui/button'
import { Badge, Card, CardHeader, PageHeader } from '@/components/ui/card'
import { ErrorBox } from '@/components/ui/feedback'
import { Field, Input, Switch } from '@/components/ui/form'
import { useTitle } from '@/lib/hooks'

function AccountCard({ me }: { me: Me }) {
  const qc = useQueryClient()
  const [name, setName] = useState(me.display_name)
  const [notify, setNotify] = useState(me.notify_errors)
  const setMe = (u: User | Me) => qc.setQueryData<Me>(keys.me, (old) => ({ ...old!, ...u }))
  const save = useMutation({
    mutationFn: () => put<{ user: Me }>('/profile', { display_name: name, notify_errors: notify }),
    onSuccess: ({ user }) => {
      setMe(user)
      toast.success('Perfil guardado')
    },
    onError: (e) => toast.error(errorList(e)[0]),
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate()
  }
  return (
    <Card aria-labelledby="cuenta">
      <CardHeader
        id="cuenta"
        title="Cuenta"
        description={<>@{me.username} {me.role === 'admin' && <Badge tone="accent" className="ml-1">admin</Badge>}</>}
      />
      <form onSubmit={submit} className="space-y-5">
        <AvatarUploader user={me} path="/profile/avatar" onChange={setMe} />
        <Field label="Nombre para mostrar">
          {(id) => <Input id={id} value={name} onChange={(e) => setName(e.target.value)} maxLength={100} required />}
        </Field>
        <Switch
          checked={notify}
          onChange={setNotify}
          label="Avisarme de errores"
          description="Por todos mis canales activos, si una comprobación automática de mis vigilancias falla."
        />
        <Button type="submit" loading={save.isPending}>Guardar perfil</Button>
      </form>
    </Card>
  )
}

function PasswordCard() {
  const [f, setF] = useState({ current_password: '', new_password: '', confirm_password: '' })
  const [errors, setErrors] = useState<string[]>([])
  const change = useMutation({
    mutationFn: () => post('/profile/password', f),
    onSuccess: () => {
      setF({ current_password: '', new_password: '', confirm_password: '' })
      toast.success('Contraseña cambiada', { description: 'Las demás sesiones abiertas se han cerrado.' })
    },
    onError: (e) => setErrors(errorList(e)),
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    setErrors([])
    change.mutate()
  }
  const input = (k: keyof typeof f, label: string, auto: string) => (
    <Field label={label}>
      {(id) => <Input id={id} type="password" autoComplete={auto} value={f[k]} required minLength={k === 'current_password' ? undefined : 8}
        onChange={(e) => setF((s) => ({ ...s, [k]: e.target.value }))} />}
    </Field>
  )
  return (
    <Card aria-labelledby="clave">
      <CardHeader id="clave" title="Cambiar contraseña" description="Al menos 8 caracteres. Se cerrarán tus otras sesiones." />
      <form onSubmit={submit} className="space-y-4" noValidate>
        <ErrorBox errors={errors} />
        {input('current_password', 'Contraseña actual', 'current-password')}
        <div className="grid gap-4 sm:grid-cols-2">
          {input('new_password', 'Nueva contraseña', 'new-password')}
          {input('confirm_password', 'Repite la nueva contraseña', 'new-password')}
        </div>
        <Button type="submit" variant="secondary" loading={change.isPending}>Cambiar contraseña</Button>
      </form>
    </Card>
  )
}

export function ProfilePage() {
  useTitle('Mi perfil')
  const me = useMe().data!
  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <PageHeader title="Mi perfil" />
      <AccountCard me={me} />
      <ChannelList base="" routeBase="/profile" />
      <PasswordCard />
    </div>
  )
}
