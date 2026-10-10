import { useRuns } from '@/api/queries'
import { Card, PageHeader } from '@/components/ui/card'
import { LoadError, PageLoading } from '@/components/ui/feedback'
import { RunsTable } from '@/components/watch/tables'
import { useTitle } from '@/lib/hooks'

export function RunsPage() {
  useTitle('Ejecuciones')
  const runs = useRuns(200)
  if (runs.isPending) return <PageLoading />
  if (runs.isError) return <LoadError error={runs.error} />
  return (
    <>
      <PageHeader title="Ejecuciones" description="Cada comprobación de cada web, automática o manual (las 200 últimas)." />
      <Card>
        {runs.data.length ? <RunsTable runs={runs.data} full /> : <p className="text-sm text-muted">Sin ejecuciones todavía.</p>}
      </Card>
    </>
  )
}
