import { AlertDialog } from 'radix-ui'
import type { ReactNode } from 'react'
import { Button, buttonClass } from './button'

/** Confirmación accesible (foco atrapado, Escape cierra) para acciones que no se pueden deshacer. */
export function ConfirmDialog({ trigger, title, description, confirm = 'Eliminar', onConfirm, loading }: {
  trigger: ReactNode
  title: string
  description: ReactNode
  confirm?: string
  onConfirm: () => void
  loading?: boolean
}) {
  return (
    <AlertDialog.Root>
      <AlertDialog.Trigger asChild>{trigger}</AlertDialog.Trigger>
      <AlertDialog.Portal>
        <AlertDialog.Overlay className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm data-[state=open]:animate-[fade-in_150ms_ease-out]" />
        <AlertDialog.Content className="fixed top-1/2 left-1/2 z-50 w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-line bg-surface p-6 shadow-2xl data-[state=open]:animate-[pop-in_180ms_ease-out]">
          <AlertDialog.Title className="text-lg font-semibold">{title}</AlertDialog.Title>
          <AlertDialog.Description className="mt-2 text-sm text-muted">{description}</AlertDialog.Description>
          <div className="mt-6 flex justify-end gap-2">
            <AlertDialog.Cancel className={buttonClass('secondary')}>Cancelar</AlertDialog.Cancel>
            <AlertDialog.Action asChild>
              <Button variant="danger" onClick={onConfirm} loading={loading}>{confirm}</Button>
            </AlertDialog.Action>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  )
}
