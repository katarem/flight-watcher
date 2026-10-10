import { AlertTriangle, Loader2 } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

export const Spinner = ({ className }: { className?: string }) => (
  <Loader2 className={cn('animate-spin', className)} aria-hidden="true" />
)

export const Skeleton = ({ className }: { className?: string }) => (
  <div className={cn('animate-pulse rounded-xl bg-surface-2', className)} aria-hidden="true" />
)

/** Carga de una página entera (con texto para lectores de pantalla). */
export function PageLoading({ label = 'Cargando…' }: { label?: string }) {
  return (
    <div className="space-y-4" role="status" aria-live="polite">
      <span className="sr-only">{label}</span>
      <Skeleton className="h-9 w-64" />
      <div className="grid gap-4 md:grid-cols-2">
        <Skeleton className="h-48" />
        <Skeleton className="h-48" />
      </div>
    </div>
  )
}

/** Lista de errores del servidor (validaciones en castellano). */
export function ErrorBox({ errors, className }: { errors: string[]; className?: string }) {
  return (
    <AnimatePresence initial={false}>
      {errors.length > 0 && (
        <motion.div
          role="alert"
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: 'auto' }}
          exit={{ opacity: 0, height: 0 }}
          className={cn('overflow-hidden', className)}
        >
          <div className="flex gap-3 rounded-xl border border-danger/30 bg-danger/8 p-3 text-sm text-danger">
            <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            {errors.length === 1 ? (
              <p>{errors[0]}</p>
            ) : (
              <ul className="list-disc space-y-0.5 pl-4">
                {errors.map((e) => (
                  <li key={e}>{e}</li>
                ))}
              </ul>
            )}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

export function EmptyState({ icon, title, children, action }: {
  icon: ReactNode
  title: string
  children?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-2xl border border-dashed border-line px-6 py-12 text-center">
      <div className="grid size-14 place-items-center rounded-2xl bg-accent-soft text-accent [&_svg]:size-7">{icon}</div>
      <h2 className="text-lg font-semibold">{title}</h2>
      {children && <div className="max-w-md text-sm text-muted">{children}</div>}
      {action}
    </div>
  )
}

/** Error al cargar una página (p. ej. 404 de una vigilancia que no es tuya). */
export function LoadError({ error }: { error: unknown }) {
  const msg = error instanceof Error ? error.message : 'No se ha podido cargar.'
  return (
    <EmptyState icon={<AlertTriangle />} title="No se ha podido cargar">
      {msg}
    </EmptyState>
  )
}
