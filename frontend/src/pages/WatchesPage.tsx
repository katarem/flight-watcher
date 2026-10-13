import { Plus } from 'lucide-react'
import { motion } from 'motion/react'
import { Link } from 'react-router'
import { useWatches } from '@/api/queries'
import type { KindKey } from '@/api/types'
import { buttonClass } from '@/components/ui/button'
import { PageHeader } from '@/components/ui/card'
import { EmptyState, LoadError, PageLoading } from '@/components/ui/feedback'
import { WatchCard } from '@/components/watch/WatchCard'
import { useTitle } from '@/lib/hooks'
import { KIND_ICONS, kindSection, useKind } from '@/lib/kinds'

/** Apartado de un transporte (hoy, «Vuelos»): sus vigilancias con el mejor precio de cada web. */
export function WatchesPage({ kind }: { kind: KindKey }) {
  const k = useKind(kind)
  useTitle(k.label)
  const watches = useWatches(kind)
  const Icon = KIND_ICONS[kind]
  const section = kindSection(kind)

  if (watches.isPending) return <PageLoading />
  if (watches.isError) return <LoadError error={watches.error} />
  const list = watches.data
  const deals = list.reduce((n, w) => n + w.stats.filter((s) => s.best?.deal).length, 0)

  return (
    <>
      <PageHeader
        title={k.label}
        description={
          list.length
            ? `${list.length} ${list.length === 1 ? 'vigilancia' : 'vigilancias'} de ${k.plural} · ${deals ? `${deals} con chollo ahora mismo` : 'ningún chollo ahora mismo'}`
            : `Empieza creando tu primera vigilancia de ${k.plural}.`
        }
        actions={<Link to={`${section}/new`} className={buttonClass()}><Plus /> Nueva vigilancia</Link>}
      />

      {list.length === 0 ? (
        <EmptyState
          icon={<Icon />}
          title="Aún no hay vigilancias"
          action={<Link to={`${section}/new`} className={buttonClass()}><Plus /> Crear la primera</Link>}
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
    </>
  )
}
