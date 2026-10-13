import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Bell, BellOff, MoreHorizontal, Pause, Pencil, Play } from 'lucide-react'
import { Link } from 'react-router'
import { toast } from 'sonner'
import { errorList, post } from '@/api/client'
import { keys, useStatus } from '@/api/queries'
import type { WatchCard as WatchCardData } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Badge, Card } from '@/components/ui/card'
import { Menu, MenuContent, MenuItem, MenuTrigger } from '@/components/ui/menu'
import { ProviderTile } from '@/components/watch/ProviderTile'
import { RoutePill, rulesText } from '@/components/watch/rules'
import { Sparkline } from '@/components/watch/Sparkline'
import { fmtPrice } from '@/lib/format'
import { useRunNow } from '@/lib/hooks'
import { useKind, watchPath } from '@/lib/kinds'

/** Tarjeta de una vigilancia: reglas, canales, mejor precio por web y acciones. */
export function WatchCard({ w }: { w: WatchCardData }) {
  const qc = useQueryClient()
  const run = useRunNow()
  const running = useStatus().data?.running
  const toggle = useMutation({
    mutationFn: () => post(`/watches/${w.id}/toggle`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.watches })
      toast.success(w.enabled ? `«${w.name}» en pausa` : `«${w.name}» reanudada`)
    },
    onError: (e) => toast.error(errorList(e)[0]),
  })
  const kind = useKind(w.kind)
  const best = w.stats.map((s) => s.best?.price).filter((p): p is number => p != null)
  const min = best.length ? Math.min(...best) : null

  return (
    <Card className={w.enabled ? '' : 'opacity-75'} aria-labelledby={`w${w.id}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <h2 id={`w${w.id}`} className="text-lg font-semibold tracking-tight">
              <Link to={watchPath(w.kind, w.id)} className="hover:underline">{w.name}</Link>
            </h2>
            <RoutePill origin={w.origin} destination={w.destination} />
            {!w.enabled && <Badge tone="warn">en pausa</Badge>}
          </div>
          <p className="text-sm text-muted">{rulesText(w)}</p>
          <p className="flex items-center gap-1.5 text-xs text-muted [&_svg]:size-3.5">
            {w.channels.length ? (
              <><Bell aria-hidden="true" /> Avisa a: {w.channels.join(', ')}</>
            ) : (
              <><BellOff aria-hidden="true" className="text-warn" /> Sin canales de aviso:{' '}
                <Link to={watchPath(w.kind, w.id, '/edit')} className="text-accent underline underline-offset-2">asígnalos</Link></>
            )}
          </p>
        </div>
        <div className="flex items-center gap-3">
          {min != null && (
            <div className="hidden items-center gap-2 sm:flex">
              <Sparkline data={w.trend} />
              <div className="text-right">
                <p className="text-xs text-muted">desde</p>
                <p className="text-lg font-semibold tabular-nums">{fmtPrice(min)}</p>
              </div>
            </div>
          )}
          <Button size="sm" variant="secondary" onClick={() => run.mutate(w.id)} disabled={running} loading={run.isPending}>
            {!run.isPending && <Play />} Comprobar
          </Button>
          <Menu>
            <MenuTrigger asChild>
              <Button size="icon" variant="ghost" aria-label={`Más acciones de ${w.name}`}><MoreHorizontal /></Button>
            </MenuTrigger>
            <MenuContent>
              <MenuItem onSelect={() => toggle.mutate()}>
                {w.enabled ? <><Pause /> Pausar</> : <><Play /> Reanudar</>}
              </MenuItem>
              <MenuItem asChild>
                <Link to={watchPath(w.kind, w.id, '/edit')}><Pencil /> Editar</Link>
              </MenuItem>
            </MenuContent>
          </Menu>
        </div>
      </div>
      {w.stats.length > 0 && (
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {w.stats.map((s) => <ProviderTile key={s.key} stat={s} plural={kind.plural} />)}
        </div>
      )}
    </Card>
  )
}
