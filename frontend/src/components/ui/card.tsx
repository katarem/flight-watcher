import type { ComponentProps, ReactNode } from 'react'
import { cn } from '@/lib/cn'

export const Card = ({ className, ...rest }: ComponentProps<'section'>) => (
  <section className={cn('min-w-0 rounded-2xl border border-line bg-surface p-4 shadow-card sm:p-5', className)} {...rest} />
)

export function CardHeader({ title, description, actions, id }: {
  title: ReactNode
  description?: ReactNode
  actions?: ReactNode
  id?: string
}) {
  return (
    <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <h2 id={id} className="text-base font-semibold tracking-tight">{title}</h2>
        {description && <p className="mt-0.5 text-sm text-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

export function PageHeader({ title, description, actions, back }: {
  title: ReactNode
  description?: ReactNode
  actions?: ReactNode
  back?: ReactNode
}) {
  return (
    <header className="mb-6 space-y-2">
      {back}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">{title}</h1>
          {description && <div className="mt-1 text-sm text-muted">{description}</div>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </header>
  )
}

export function Badge({ tone = 'neutral', children, className }: {
  tone?: 'neutral' | 'deal' | 'danger' | 'warn' | 'accent'
  children: ReactNode
  className?: string
}) {
  const tones = {
    neutral: 'bg-surface-2 text-muted',
    deal: 'bg-deal/15 text-deal',
    danger: 'bg-danger/12 text-danger',
    warn: 'bg-warn/15 text-warn',
    accent: 'bg-accent-soft text-accent',
  }
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold [&_svg]:size-3', tones[tone], className)}>
      {children}
    </span>
  )
}

/** Tabla con desplazamiento horizontal propio (no ensancha la página en móvil). */
export const TableWrap = ({ children, label }: { children: ReactNode; label?: string }) => (
  <div className="relative -mx-4 overflow-x-auto px-4 sm:-mx-5 sm:px-5" role="region" aria-label={label} tabIndex={label ? 0 : undefined}>
    {children}
  </div>
)

export const tableClass =
  'w-full border-collapse text-sm [&_td]:border-t [&_td]:border-line [&_td]:px-2 [&_td]:py-2 [&_th]:px-2 [&_th]:pb-2 ' +
  '[&_th]:text-left [&_th]:text-xs [&_th]:font-medium [&_th]:uppercase [&_th]:tracking-wide [&_th]:text-muted ' +
  '[&_tr:first-child>td]:border-t-0 [&_thead+tbody_tr:first-child>td]:border-t'
