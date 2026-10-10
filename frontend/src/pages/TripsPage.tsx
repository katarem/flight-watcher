import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Bell, BellOff, Luggage, MoreHorizontal, Pause, Pencil, Play, Plus } from 'lucide-react'
import { motion } from 'motion/react'
import { Link } from 'react-router'
import { toast } from 'sonner'
import { errorList, post } from '@/api/client'
import { keys, useStatus, useTrips } from '@/api/queries'
import type { TripCard as TripCardData } from '@/api/types'
import { Button, buttonClass } from '@/components/ui/button'
import { Badge, Card, PageHeader } from '@/components/ui/card'
import { EmptyState, LoadError, PageLoading } from '@/components/ui/feedback'
import { Menu, MenuContent, MenuItem, MenuTrigger } from '@/components/ui/menu'
import { BestCombo, TripLegs, TripPill, TripWarnings, tripRulesText } from '@/components/trip/parts'
import { Sparkline } from '@/components/watch/Sparkline'
import { fmtPrice } from '@/lib/format'
import { useRunTrip, useTitle } from '@/lib/hooks'

function TripCard({ t }: { t: TripCardData }) {
  const qc = useQueryClient()
  const run = useRunTrip()
  const running = useStatus().data?.running
  const toggle = useMutation({
    mutationFn: () => post(`/trips/${t.id}/toggle`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.trips })
      toast.success(t.enabled ? `«${t.name}» en pausa` : `«${t.name}» reanudado`)
    },
    onError: (e) => toast.error(errorList(e)[0]),
  })

  return (
    <Card className={t.enabled ? '' : 'opacity-75'} aria-labelledby={`t${t.id}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <h2 id={`t${t.id}`} className="text-lg font-semibold tracking-tight">
              <Link to={`/trips/${t.id}`} className="hover:underline">{t.name}</Link>
            </h2>
            <TripPill trip={t} />
            {!t.enabled && <Badge tone="warn">en pausa</Badge>}
          </div>
          <p className="text-sm text-muted">{tripRulesText(t)}</p>
          <TripLegs trip={t} />
          <p className="flex items-center gap-1.5 text-xs text-muted [&_svg]:size-3.5">
            {t.channels.length ? (
              <><Bell aria-hidden="true" /> Avisa a: {t.channels.join(', ')}</>
            ) : (
              <><BellOff aria-hidden="true" className="text-warn" /> Sin canales de aviso:{' '}
                <Link to={`/trips/${t.id}/edit`} className="text-accent underline underline-offset-2">asígnalos</Link></>
            )}
          </p>
        </div>
        <div className="flex items-center gap-3">
          {t.best && (
            <div className="hidden items-center gap-2 sm:flex">
              <Sparkline data={t.trend} />
              <div className="text-right">
                <p className="text-xs text-muted">desde</p>
                <p className="text-lg font-semibold tabular-nums">{fmtPrice(t.best.total)}</p>
              </div>
            </div>
          )}
          <Button size="sm" variant="secondary" onClick={() => run.mutate(t.id)} disabled={running} loading={run.isPending}>
            {!run.isPending && <Play />} Comprobar
          </Button>
          <Menu>
            <MenuTrigger asChild>
              <Button size="icon" variant="ghost" aria-label={`Más acciones de ${t.name}`}><MoreHorizontal /></Button>
            </MenuTrigger>
            <MenuContent>
              <MenuItem onSelect={() => toggle.mutate()}>
                {t.enabled ? <><Pause /> Pausar</> : <><Play /> Reanudar</>}
              </MenuItem>
              <MenuItem asChild>
                <Link to={`/trips/${t.id}/edit`}><Pencil /> Editar</Link>
              </MenuItem>
            </MenuContent>
          </Menu>
        </div>
      </div>
      <div className="mt-4 space-y-3">
        <TripWarnings warnings={t.warnings} />
        <BestCombo combo={t.best} base={t.base} nDates={t.n_dates} className="sm:max-w-md" />
      </div>
    </Card>
  )
}

export function TripsPage() {
  useTitle('Viajes')
  const trips = useTrips()

  if (trips.isPending) return <PageLoading />
  if (trips.isError) return <LoadError error={trips.error} />
  const list = trips.data
  const deals = list.filter((t) => t.best?.deal).length

  return (
    <>
      <PageHeader
        title="Viajes"
        description={
          list.length
            ? `${list.length} ${list.length === 1 ? 'viaje' : 'viajes'} · ${deals ? `${deals} con chollo ahora mismo` : 'ningún chollo ahora mismo'}`
            : 'Junta una vigilancia de ida y otra de vuelta para vigilar el precio del viaje completo.'
        }
        actions={<Link to="/trips/new" className={buttonClass()}><Plus /> Nuevo viaje</Link>}
      />

      {list.length === 0 ? (
        <EmptyState
          icon={<Luggage />}
          title="Aún no hay viajes"
          action={<Link to="/trips/new" className={buttonClass()}><Plus /> Crear el primero</Link>}
        >
          Un viaje junta la vigilancia de ida y la de vuelta con las noches que quieres quedarte, y te avisa cuando
          el total (ida + vuelta) baja de lo que marques o de lo habitual.
        </EmptyState>
      ) : (
        <motion.div
          className="space-y-4"
          initial="hidden"
          animate="show"
          variants={{ show: { transition: { staggerChildren: 0.06 } } }}
        >
          {list.map((t) => (
            <motion.div key={t.id} variants={{ hidden: { opacity: 0, y: 12 }, show: { opacity: 1, y: 0 } }}>
              <TripCard t={t} />
            </motion.div>
          ))}
        </motion.div>
      )}
    </>
  )
}
