import { Bell, MessageCircle, Send } from 'lucide-react'
import { cn } from '@/lib/cn'

const styles: Record<string, { cls: string; icon: React.ReactNode }> = {
  discord: { cls: 'bg-[#5865f2]/15 text-[#5865f2]', icon: <MessageCircle /> },
  telegram: { cls: 'bg-[#229ed9]/15 text-[#229ed9]', icon: <Send /> },
}

/** Icono del tipo de canal (Discord, Telegram…). */
export function KindIcon({ kind, className }: { kind: string; className?: string }) {
  const s = styles[kind] ?? { cls: 'bg-surface-2 text-muted', icon: <Bell /> }
  return (
    <span aria-hidden="true" className={cn('grid size-10 shrink-0 place-items-center rounded-xl [&_svg]:size-5', s.cls, className)}>
      {s.icon}
    </span>
  )
}
