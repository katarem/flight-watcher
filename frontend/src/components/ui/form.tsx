import { Checkbox as RCheckbox, Switch as RSwitch } from 'radix-ui'
import { Check } from 'lucide-react'
import { forwardRef, useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from 'react'
import { cn } from '@/lib/cn'

const control =
  'h-10 w-full rounded-xl border border-line bg-surface px-3 text-sm text-fg shadow-sm transition ' +
  'placeholder:text-muted/70 hover:border-muted/50 focus:border-accent focus:outline-none focus:ring-3 focus:ring-accent/20 ' +
  'disabled:opacity-60'

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, ...rest }, ref,
) {
  return <input ref={ref} className={cn(control, className)} {...rest} />
})

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function Select(
  { className, ...rest }, ref,
) {
  return <select ref={ref} className={cn(control, 'appearance-auto pr-8', className)} {...rest} />
})

/** Etiqueta + control + ayuda. El control recibe el id para que la etiqueta lo nombre. */
export function Field({ label, hint, children, className }: {
  label: ReactNode
  hint?: ReactNode
  children: (id: string, describedBy?: string) => ReactNode
  className?: string
}) {
  const id = useId()
  const hintId = hint ? `${id}-hint` : undefined
  return (
    <div className={cn('space-y-1.5', className)}>
      <label htmlFor={id} className="block text-sm font-medium">{label}</label>
      {children(id, hintId)}
      {hint && <p id={hintId} className="text-xs text-muted">{hint}</p>}
    </div>
  )
}

export function Switch({ checked, onChange, label, description, disabled }: {
  checked: boolean
  onChange: (v: boolean) => void
  label: ReactNode
  description?: ReactNode
  disabled?: boolean
}) {
  const id = useId()
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="min-w-0">
        <label htmlFor={id} className="text-sm font-medium">{label}</label>
        {description && <p className="text-xs text-muted">{description}</p>}
      </div>
      <RSwitch.Root
        id={id}
        checked={checked}
        onCheckedChange={onChange}
        disabled={disabled}
        className="relative h-6 w-11 shrink-0 rounded-full bg-line transition-colors data-[state=checked]:bg-accent disabled:opacity-50"
      >
        <RSwitch.Thumb className="block size-5 translate-x-0.5 rounded-full bg-white shadow transition-transform duration-200 data-[state=checked]:translate-x-[22px]" />
      </RSwitch.Root>
    </div>
  )
}

export function Checkbox({ checked, onChange, children, className, disabled, describedBy }: {
  checked: boolean
  onChange: (v: boolean) => void
  children: ReactNode
  className?: string
  disabled?: boolean
  describedBy?: string
}) {
  const id = useId()
  return (
    <div className={cn('flex items-center gap-2.5', className)}>
      <RCheckbox.Root
        id={id}
        checked={checked}
        disabled={disabled}
        aria-describedby={describedBy}
        onCheckedChange={(v) => onChange(v === true)}
        className="grid size-5 shrink-0 place-items-center rounded-md border border-line bg-surface shadow-sm transition disabled:opacity-50 data-[state=checked]:border-accent data-[state=checked]:bg-accent"
      >
        <RCheckbox.Indicator>
          <Check className="size-3.5 text-accent-fg" strokeWidth={3} aria-hidden="true" />
        </RCheckbox.Indicator>
      </RCheckbox.Root>
      <label htmlFor={id} className="flex min-w-0 flex-wrap items-center gap-2 text-sm">{children}</label>
    </div>
  )
}

/** Grupo de campos con título (en formularios largos). */
export function FormSection({ title, description, children }: { title: string; description?: ReactNode; children: ReactNode }) {
  return (
    <fieldset className="space-y-4 rounded-2xl border border-line bg-surface p-4 shadow-card sm:p-5">
      <legend className="sr-only">{title}</legend>
      <div aria-hidden="true">
        <h2 className="text-base font-semibold tracking-tight">{title}</h2>
        {description && <p className="mt-0.5 text-sm text-muted">{description}</p>}
      </div>
      {children}
    </fieldset>
  )
}
