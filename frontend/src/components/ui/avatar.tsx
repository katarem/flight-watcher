import { cn } from '@/lib/cn'

const sizes = { sm: 'size-8 text-sm', md: 'size-10 text-base', lg: 'size-20 text-3xl' }

/** Avatar redondo: la imagen subida o, si no hay, la inicial sobre un color derivado del id. */
export function Avatar({ user, size = 'md', className }: {
  user: { id: number; avatar: string | null; display_name: string; username: string }
  size?: keyof typeof sizes
  className?: string
}) {
  const cls = cn('shrink-0 rounded-full object-cover ring-2 ring-surface', sizes[size], className)
  if (user.avatar) return <img src={`/avatars/${user.avatar}`} alt="" className={cls} loading="lazy" />
  const hue = (user.id * 47) % 360
  return (
    <span
      aria-hidden="true"
      className={cn(cls, 'grid place-items-center font-semibold text-white')}
      style={{ background: `linear-gradient(135deg, hsl(${hue} 65% 55%), hsl(${(hue + 40) % 360} 65% 45%))` }}
    >
      {(user.display_name || user.username || '?').slice(0, 1).toUpperCase()}
    </span>
  )
}
