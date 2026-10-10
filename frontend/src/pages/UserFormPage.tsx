import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ChevronLeft } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { toast } from 'sonner'
import { errorList, post, put } from '@/api/client'
import { keys, useMe, useUser } from '@/api/queries'
import type { Me, User } from '@/api/types'
import { AvatarUploader } from '@/components/account/AvatarUploader'
import { ChannelList } from '@/components/account/ChannelList'
import { Button, buttonClass } from '@/components/ui/button'
import { PageHeader } from '@/components/ui/card'
import { ErrorBox, LoadError, PageLoading } from '@/components/ui/feedback'
import { Field, FormSection, Input, Select, Switch } from '@/components/ui/form'
import { useTitle } from '@/lib/hooks'

function UserForm({ user }: { user?: User }) {
  const me = useMe().data!
  const qc = useQueryClient()
  const navigate = useNavigate()
  const isSelf = user?.id === me.id
  const [f, setF] = useState({
    username: user?.username ?? '', display_name: user?.display_name ?? '', password: '',
    role: user?.role ?? 'user', enabled: user?.enabled ?? true,
  })
  const [errors, setErrors] = useState<string[]>([])
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((s) => ({ ...s, [k]: v }))

  const save = useMutation({
    mutationFn: () => (user ? put<{ user: User }>(`/users/${user.id}`, f) : post<{ user: User }>('/users', f)),
    onSuccess: ({ user: saved }) => {
      qc.invalidateQueries({ queryKey: keys.users })
      if (isSelf) qc.setQueryData<Me>(keys.me, (old) => ({ ...old!, ...saved }))
      toast.success(user ? `Usuario «${saved.username}» actualizado` : `Usuario «${saved.username}» creado`, {
        description: user ? undefined : 'Ya puedes añadirle avatar y canales de aviso.',
      })
      navigate(user ? '/admin/users' : `/admin/users/${saved.id}/edit`)
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
      <FormSection title="Datos de la cuenta">
        {user && (
          <AvatarUploader user={user} path={`/users/${user.id}/avatar`} onChange={(u) => {
            qc.setQueryData(keys.user(user.id), u)
            qc.invalidateQueries({ queryKey: keys.users })
            if (isSelf) qc.setQueryData<Me>(keys.me, (old) => ({ ...old!, ...u }))
          }} />
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Usuario" hint="3-32 caracteres: letras, números, punto, guion o guion bajo.">
            {(id, hint) => <Input id={id} aria-describedby={hint} value={f.username} onChange={(e) => set('username', e.target.value)}
              required maxLength={32} autoCapitalize="none" autoComplete="off" spellCheck={false} />}
          </Field>
          <Field label="Nombre para mostrar">
            {(id) => <Input id={id} value={f.display_name} onChange={(e) => set('display_name', e.target.value)} maxLength={100}
              placeholder="Como se verá en el panel" />}
          </Field>
          <Field label={user ? 'Nueva contraseña' : 'Contraseña'} hint={user ? 'Vacía = no cambiarla.' : 'Al menos 8 caracteres.'}>
            {(id, hint) => <Input id={id} aria-describedby={hint} type="password" autoComplete="new-password" value={f.password}
              onChange={(e) => set('password', e.target.value)} required={!user} minLength={8} />}
          </Field>
          <Field label="Rol" hint={isSelf ? 'No puedes cambiar tu propio rol.' : 'El administrador gestiona usuarios y los ajustes globales.'}>
            {(id, hint) => (
              <Select id={id} aria-describedby={hint} value={f.role} disabled={isSelf}
                onChange={(e) => set('role', e.target.value as User['role'])}>
                <option value="user">Usuario</option>
                <option value="admin">Administrador</option>
              </Select>
            )}
          </Field>
        </div>
        <Switch checked={f.enabled} onChange={(v) => set('enabled', v)} disabled={isSelf} label="Cuenta activa"
          description={isSelf ? 'No puedes desactivarte a ti mismo.' : 'Desactivada no puede entrar y sus vigilancias no se comprueban.'} />
      </FormSection>
      <div className="flex gap-2">
        <Button type="submit" loading={save.isPending}>{user ? 'Guardar cambios' : 'Crear usuario'}</Button>
        <Link to="/admin/users" className={buttonClass('ghost')}>Cancelar</Link>
      </div>
    </form>
  )
}

export function UserFormPage() {
  const { uid } = useParams()
  const id = uid ? Number(uid) : null
  const user = useUser(id)
  useTitle(id ? 'Editar usuario' : 'Nuevo usuario')
  if (id != null && user.isPending) return <PageLoading />
  if (id != null && user.isError) return <LoadError error={user.error} />

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <PageHeader
        back={<Link to="/admin/users" className="inline-flex items-center gap-1 text-sm text-muted hover:text-fg"><ChevronLeft className="size-4" aria-hidden="true" /> Usuarios</Link>}
        title={user.data ? `Editar @${user.data.username}` : 'Nuevo usuario'}
      />
      <UserForm key={id ?? 'new'} user={user.data} />
      {user.data && (
        <ChannelList
          base={`/users/${user.data.id}`}
          routeBase={`/admin/users/${user.data.id}`}
          title={`Canales de aviso de @${user.data.username}`}
          description="Puedes configurarlos por quien no sepa hacerlo: el usuario los verá en su perfil y los asignará a sus vigilancias. Los secretos guardados no se muestran."
        />
      )}
    </div>
  )
}
