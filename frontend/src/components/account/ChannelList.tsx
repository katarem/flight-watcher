import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Pencil, Plus, Send, Trash2 } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { Link } from 'react-router'
import { toast } from 'sonner'
import { del, errorList, post } from '@/api/client'
import { keys, useChannels } from '@/api/queries'
import type { Channel } from '@/api/types'
import { Button, buttonClass } from '@/components/ui/button'
import { Badge, Card, CardHeader } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/feedback'
import { KindIcon } from './KindIcon'

/** Canales de un usuario. `base` es '' (los propios) o '/users/{id}' (admin); `routeBase` es /profile o /admin/users/{id}. */
export function ChannelList({ base, routeBase, title = 'Canales de aviso', description }: {
  base: string
  routeBase: string
  title?: string
  description?: string
}) {
  const channels = useChannels(base)
  const qc = useQueryClient()
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['channels'] })
    qc.invalidateQueries({ queryKey: keys.watches })
  }
  const test = useMutation({
    mutationFn: (c: Channel) => post(`${base}/channels/${c.id}/test`),
    onSuccess: (_d, c) => toast.success(`Mensaje de prueba enviado a «${c.name}»`),
    onError: (e) => toast.error(errorList(e)[0]),
  })
  const remove = useMutation({
    mutationFn: (c: Channel) => del(`${base}/channels/${c.id}`),
    onSuccess: (_d, c) => {
      refresh()
      toast.success(`Canal «${c.name}» eliminado (también de las vigilancias que lo usaban)`)
    },
    onError: (e) => toast.error(errorList(e)[0]),
  })

  return (
    <Card aria-labelledby={`canales${base}`}>
      <CardHeader
        id={`canales${base}`}
        title={title}
        description={description ?? 'Cada vigilancia avisa solo a los canales que marques en su formulario. Puedes tener varios de cada tipo.'}
        actions={<Link to={`${routeBase}/channels/new`} className={buttonClass('primary', 'sm')}><Plus /> Añadir canal</Link>}
      />
      {channels.isPending ? <Skeleton className="h-16" /> : !channels.data?.length ? (
        <p className="text-sm text-muted">Todavía no hay ningún canal. Añade uno (Discord o Telegram) y asígnalo a las vigilancias que quieras.</p>
      ) : (
        <ul className="divide-y divide-line">
          <AnimatePresence initial={false}>
            {channels.data.map((c) => (
              <motion.li key={c.id} layout exit={{ opacity: 0, height: 0 }} className="flex flex-wrap items-center justify-between gap-3 py-3">
                <div className="flex min-w-0 items-center gap-3">
                  <KindIcon kind={c.kind} />
                  <div className="min-w-0">
                    <p className="truncate font-medium">{c.name}</p>
                    <div className="flex gap-1.5">
                      <Badge tone="accent">{c.kind_label}</Badge>
                      {!c.enabled && <Badge tone="warn">pausado</Badge>}
                    </div>
                  </div>
                </div>
                <div className="flex flex-wrap gap-1">
                  <Button variant="ghost" size="sm" onClick={() => test.mutate(c)} loading={test.isPending && test.variables?.id === c.id}>
                    <Send /> Probar
                  </Button>
                  <Link to={`${routeBase}/channels/${c.id}/edit`} className={buttonClass('ghost', 'sm')}><Pencil /> Editar</Link>
                  <ConfirmDialog
                    trigger={<Button variant="ghost" size="sm" className="text-danger"><Trash2 /> Eliminar</Button>}
                    title={`¿Eliminar el canal «${c.name}»?`}
                    description="Dejará de avisar en las vigilancias que lo usan."
                    onConfirm={() => remove.mutate(c)}
                  />
                </div>
              </motion.li>
            ))}
          </AnimatePresence>
        </ul>
      )}
    </Card>
  )
}
