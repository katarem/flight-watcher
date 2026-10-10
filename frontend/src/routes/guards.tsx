import { Plane } from 'lucide-react'
import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router'
import { useMe } from '@/api/queries'
import { EmptyState } from '@/components/ui/feedback'

function Splash() {
  return (
    <div className="grid min-h-dvh place-items-center" role="status" aria-live="polite">
      <Plane className="size-8 animate-pulse text-accent" aria-hidden="true" />
      <span className="sr-only">Cargando…</span>
    </div>
  )
}

/** Solo con sesión: si no, al login recordando a dónde se quería ir. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { data: me, isPending } = useMe()
  const loc = useLocation()
  if (isPending) return <Splash />
  if (!me) {
    const next = loc.pathname + loc.search
    return <Navigate to={next === '/' ? '/login' : `/login?next=${encodeURIComponent(next)}`} replace />
  }
  return children
}

export function RequireAdmin({ children }: { children: ReactNode }) {
  const { data: me } = useMe()
  if (me?.role !== 'admin')
    return <EmptyState icon={<Plane />} title="Solo para administradores">Esta sección solo la ven los administradores.</EmptyState>
  return children
}
