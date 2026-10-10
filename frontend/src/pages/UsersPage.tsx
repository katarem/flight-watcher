import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Pencil, Trash2, UserPlus } from 'lucide-react'
import { Link } from 'react-router'
import { toast } from 'sonner'
import { del, errorList } from '@/api/client'
import { keys, useMe, useUsers } from '@/api/queries'
import type { AdminUser } from '@/api/types'
import { Avatar } from '@/components/ui/avatar'
import { Button, buttonClass } from '@/components/ui/button'
import { Badge, Card, PageHeader, TableWrap, tableClass } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/dialog'
import { LoadError, PageLoading } from '@/components/ui/feedback'
import { fmtDateTime } from '@/lib/format'
import { useTitle } from '@/lib/hooks'

export function UsersPage() {
  useTitle('Usuarios')
  const users = useUsers()
  const me = useMe().data!
  const qc = useQueryClient()
  const remove = useMutation({
    mutationFn: (u: AdminUser) => del(`/users/${u.id}`),
    onSuccess: (_d, u) => {
      qc.invalidateQueries({ queryKey: keys.users })
      toast.success(`Usuario «${u.username}» eliminado junto con sus vigilancias`)
    },
    onError: (e) => toast.error(errorList(e)[0]),
  })

  if (users.isPending) return <PageLoading />
  if (users.isError) return <LoadError error={users.error} />

  return (
    <>
      <PageHeader
        title="Usuarios"
        description="Cada usuario ve y gestiona solo sus vigilancias y sus canales. Un usuario desactivado no puede entrar y sus vigilancias no se comprueban."
        actions={<Link to="/admin/users/new" className={buttonClass()}><UserPlus /> Nuevo usuario</Link>}
      />
      <Card>
        <TableWrap label="Usuarios">
          <table className={tableClass}>
            <thead>
              <tr>
                <th scope="col">Usuario</th>
                <th scope="col">Rol</th>
                <th scope="col">Estado</th>
                <th scope="col" className="text-right!">Vigilancias</th>
                <th scope="col" className="text-right!">Canales</th>
                <th scope="col">Alta</th>
                <th scope="col"><span className="sr-only">Acciones</span></th>
              </tr>
            </thead>
            <tbody>
              {users.data.map((u) => (
                <tr key={u.id}>
                  <td>
                    <div className="flex items-center gap-3">
                      <Avatar user={u} size="sm" />
                      <div className="min-w-0">
                        <p className="truncate font-medium">{u.display_name}</p>
                        <p className="text-xs text-muted">@{u.username}</p>
                      </div>
                    </div>
                  </td>
                  <td>{u.role === 'admin' ? <Badge tone="accent">admin</Badge> : <span className="text-muted">usuario</span>}</td>
                  <td>{u.enabled ? <Badge tone="deal">activo</Badge> : <Badge tone="warn">desactivado</Badge>}</td>
                  <td className="text-right tabular-nums">{u.n_watches}</td>
                  <td className="text-right tabular-nums">{u.n_channels}</td>
                  <td className="whitespace-nowrap text-muted">{fmtDateTime(u.created_at).slice(0, 10)}</td>
                  <td>
                    <div className="flex justify-end gap-1">
                      <Link to={`/admin/users/${u.id}/edit`} className={buttonClass('ghost', 'sm')} aria-label={`Editar a ${u.username}`}>
                        <Pencil /> <span className="hidden sm:inline">Editar</span>
                      </Link>
                      {u.id !== me.id && (
                        <ConfirmDialog
                          trigger={<Button variant="ghost" size="sm" className="text-danger" aria-label={`Eliminar a ${u.username}`}><Trash2 /></Button>}
                          title={`¿Eliminar a @${u.username}?`}
                          description="Se borrarán también todas sus vigilancias con su histórico y sus canales de aviso."
                          onConfirm={() => remove.mutate(u)}
                        />
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      </Card>
    </>
  )
}
