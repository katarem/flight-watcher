import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { toast } from 'sonner'
import { errorList, post } from '@/api/client'
import { keys } from '@/api/queries'
import type { Status } from '@/api/types'

/** Título de la pestaña del navegador. */
export function useTitle(title: string | undefined) {
  useEffect(() => {
    document.title = title ? `${title} · Flight Watcher` : 'Flight Watcher'
  }, [title])
}

/** Lanza una comprobación (de una vigilancia o de todas las del usuario) y marca la ronda como en curso. */
export function useRunNow() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (watchId?: number) => post<{ started: boolean }>(watchId ? `/watches/${watchId}/run` : '/run'),
    onSuccess: ({ started }) => {
      if (!started) {
        toast.info('Ya hay una comprobación en marcha.')
        return
      }
      qc.setQueryData<Status>(keys.status, (s) => ({ current: '', next_run: null, ...s, running: true }))
      toast('Comprobación lanzada', { description: 'Te avisamos al terminar; puedes seguir usando el panel.' })
      setTimeout(() => qc.invalidateQueries({ queryKey: keys.status }), 800)
    },
    onError: (e) => toast.error(errorList(e)[0]),
  })
}
