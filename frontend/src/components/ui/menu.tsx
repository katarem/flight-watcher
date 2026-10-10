import { DropdownMenu } from 'radix-ui'
import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

export const Menu = DropdownMenu.Root
export const MenuTrigger = DropdownMenu.Trigger

export function MenuContent({ children, align = 'end' }: { children: ReactNode; align?: 'start' | 'end' }) {
  return (
    <DropdownMenu.Portal>
      <DropdownMenu.Content
        align={align}
        sideOffset={6}
        className="z-50 min-w-48 rounded-xl border border-line bg-surface p-1 shadow-xl data-[state=open]:animate-[pop-in_140ms_ease-out]"
      >
        {children}
      </DropdownMenu.Content>
    </DropdownMenu.Portal>
  )
}

const item =
  'flex cursor-pointer select-none items-center gap-2 rounded-lg px-2.5 py-2 text-sm outline-none ' +
  'data-[highlighted]:bg-surface-2 [&_svg]:size-4 [&_svg]:text-muted'

export function MenuItem({ children, onSelect, danger, asChild }: {
  children: ReactNode
  onSelect?: () => void
  danger?: boolean
  asChild?: boolean
}) {
  return (
    <DropdownMenu.Item asChild={asChild} onSelect={onSelect} className={cn(item, danger && 'text-danger [&_svg]:text-danger')}>
      {children}
    </DropdownMenu.Item>
  )
}

export const MenuSeparator = () => <DropdownMenu.Separator className="my-1 h-px bg-line" />

export const MenuLabel = ({ children }: { children: ReactNode }) => (
  <DropdownMenu.Label className="px-2.5 pt-2 pb-1 text-xs font-medium text-muted">{children}</DropdownMenu.Label>
)

export function MenuRadio<T extends string>({ value, onChange, options }: {
  value: T
  onChange: (v: T) => void
  options: { value: T; label: string; icon: ReactNode }[]
}) {
  return (
    <DropdownMenu.RadioGroup value={value} onValueChange={(v) => onChange(v as T)}>
      {options.map((o) => (
        <DropdownMenu.RadioItem key={o.value} value={o.value} className={cn(item, 'data-[state=checked]:text-accent data-[state=checked]:[&_svg]:text-accent')}>
          {o.icon}
          {o.label}
        </DropdownMenu.RadioItem>
      ))}
    </DropdownMenu.RadioGroup>
  )
}
