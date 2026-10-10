import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Bell, BellOff, MoreHorizontal, Pause, Pencil, Play, Plane, Plus } from 'lucide-react'
import { motion } from 'motion/react'
import { Link } from 'react-router'
import { toast } from 'sonner'
import { errorList, post } from '@/api/client'
import { keys, useAlerts, useRuns, useStatus, useWatches } from '@/api/queries'
import type { WatchCard as WatchCardData } from '@/api/types'
import { Button, buttonClass } from '@/components/ui/button'
import { Badge, Card, CardHeader, PageHeader } from '@/components/ui/card'
import { EmptyState, LoadError, PageLoading } from '@/components/ui/feedback'
import { Menu, MenuContent, MenuItem, MenuTrigger } from '@/components/ui/menu'
import { ProviderTile } from '@/components/watch/ProviderTile'
import { RoutePill, rulesText } from '@/components/watch/rules'
import { Sparkline } from '@/components/watch/Sparkline'
import { AlertsTable, RunsTable } from '@/components/watch/tables'
import { fmtPrice } from '@/lib/format'
import { useRunNow, useTitle } from '@/lib/hooks'

function WatchCard({ w }: { w: WatchCardData }) {
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
  const best = w.stats.map((s) => s.best?.price).filter((p): p is number => p != null)
  const min = best.length ? Math.min(...best) : null

  return (
    <Card className={w.enabled ? '' : 'opacity-75'} aria-labelledby={`w${w.id}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <h2 id={`w${w.id}`} className="text-lg font-semibold tracking-tight">
              <Link to={`/watches/${w.id}`} className="hover:underline">{w.name}</Link>
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
                <Link to={`/watches/${w.id}/edit`} className="text-accent underline underline-offset-2">asígnalos</Link></>
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
                <Link to={`/watches/${w.id}/edit`}><Pencil /> Editar</Link>
              </MenuItem>
            </MenuContent>
          </Menu>
        </div>
      </div>
      {w.stats.length > 0 && (
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {w.stats.map((s) => <ProviderTile key={s.key} stat={s} />)}
        </div>
      )}
    </Card>
  )
}

export function DashboardPage() {
  useTitle('Panel')
  const watches = useWatches()
  const alerts = useAlerts(8)
  const runs = useRuns(8)

  if (watches.isPending) return <PageLoading />
  if (watches.isError) return <LoadError error={watches.error} />
  const list = watches.data
  const deals = list.reduce((n, w) => n + w.stats.filter((s) => s.best?.deal).length, 0)

  return (
    <>
      <PageHeader
        title="Panel"
        description={
          list.length
            ? `${list.length} ${list.length === 1 ? 'vigilancia' : 'vigilancias'} · ${deals ? `${deals} con chollo ahora mismo` : 'ningún chollo ahora mismo'}`
            : 'Empieza creando tu primera vigilancia.'
        }
        actions={<Link to="/watches/new" className={buttonClass()}><Plus /> Nueva vigilancia</Link>}
      />

      {list.length === 0 ? (
        <EmptyState
          icon={<Plane />}
          title="Aún no hay vigilancias"
          action={<Link to="/watches/new" className={buttonClass()}><Plus /> Crear la primera</Link>}
        >
          Elige origen, destino y las webs que quieres vigilar. Te avisamos cuando el precio baje de lo que marques
          o de lo habitual.
        </EmptyState>
      ) : (
        <motion.div
          className="space-y-4"
          initial="hidden"
          animate="show"
          variants={{ show: { transition: { staggerChildren: 0.06 } } }}
        >
          {list.map((w) => (
            <motion.div key={w.id} variants={{ hidden: { opacity: 0, y: 12 }, show: { opacity: 1, y: 0 } }}>
              <WatchCard w={w} />
            </motion.div>
          ))}
        </motion.div>
      )}

      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <Card aria-labelledby="ultimos-avisos">
          <CardHeader id="ultimos-avisos" title="Últimos avisos" />
          {alerts.data?.length ? <AlertsTable alerts={alerts.data} /> : (
            <p className="text-sm text-muted">Todavía no se ha enviado ningún aviso.</p>
          )}
        </Card>
        <Card aria-labelledby="ultimas-ejecuciones">
          <CardHeader
            id="ultimas-ejecuciones"
            title="Últimas ejecuciones"
            actions={<Link to="/runs" className="text-sm text-accent hover:underline">Ver todas</Link>}
          />
          {runs.data?.length ? <RunsTable runs={runs.data} /> : <p className="text-sm text-muted">Sin ejecuciones todavía.</p>}
        </Card>
      </div>
    </>
  )
}
