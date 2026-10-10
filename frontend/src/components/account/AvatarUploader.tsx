import { useMutation } from '@tanstack/react-query'
import { Camera, Trash2 } from 'lucide-react'
import { useId, useRef } from 'react'
import { toast } from 'sonner'
import { api, errorList } from '@/api/client'
import { useMeta } from '@/api/queries'
import type { User } from '@/api/types'
import { Avatar } from '@/components/ui/avatar'
import { Button, buttonClass } from '@/components/ui/button'

const TYPES = 'image/png,image/jpeg,image/gif,image/webp'

/** Cambiar o quitar el avatar: se sube en cuanto se elige el archivo. `path` es /profile/avatar o /users/{id}/avatar. */
export function AvatarUploader({ user, path, onChange }: { user: User; path: string; onChange: (u: User) => void }) {
  const max = useMeta().data?.avatar_max_bytes ?? 2 * 1024 * 1024
  const input = useRef<HTMLInputElement>(null)
  const id = useId()
  const upload = useMutation({
    mutationFn: (file: File) => {
      const fd = new FormData()
      fd.append('avatar', file)
      return api<{ user: User }>(path, { method: 'POST', body: fd })
    },
    onSuccess: ({ user }) => {
      onChange(user)
      toast.success('Avatar actualizado')
    },
    onError: (e) => toast.error(errorList(e)[0]),
  })
  const remove = useMutation({
    mutationFn: () => api<{ user: User }>(path, { method: 'DELETE' }),
    onSuccess: ({ user }) => {
      onChange(user)
      toast.success('Avatar quitado')
    },
    onError: (e) => toast.error(errorList(e)[0]),
  })

  const pick = (file: File | undefined) => {
    if (!file) return
    if (file.size > max) toast.error('El avatar no puede pesar más de 2 MB.')
    else upload.mutate(file)
    if (input.current) input.current.value = ''
  }

  return (
    <div className="flex items-center gap-4">
      <Avatar user={user} size="lg" />
      <div className="space-y-2">
        <div className="flex flex-wrap gap-2">
          <label htmlFor={id} className={buttonClass('secondary', 'sm', 'cursor-pointer focus-within:ring-3 focus-within:ring-accent/30')}>
            <Camera /> {upload.isPending ? 'Subiendo…' : 'Cambiar avatar'}
            <input id={id} ref={input} type="file" accept={TYPES} className="sr-only" onChange={(e) => pick(e.target.files?.[0])} />
          </label>
          {user.avatar && (
            <Button variant="ghost" size="sm" onClick={() => remove.mutate()} loading={remove.isPending}>
              <Trash2 /> Quitar
            </Button>
          )}
        </div>
        <p className="text-xs text-muted">PNG, JPG, GIF o WebP de hasta 2 MB.</p>
      </div>
    </div>
  )
}
