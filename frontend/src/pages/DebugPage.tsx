import { FileText, Image } from 'lucide-react'
import { API } from '@/api/client'
import { useDebugFiles } from '@/api/queries'
import { Card, PageHeader, TableWrap, tableClass } from '@/components/ui/card'
import { LoadError, PageLoading } from '@/components/ui/feedback'
import { fmtDateTime } from '@/lib/format'
import { useTitle } from '@/lib/hooks'

export function DebugPage() {
  useTitle('Diagnóstico')
  const files = useDebugFiles()
  if (files.isPending) return <PageLoading />
  if (files.isError) return <LoadError error={files.error} />
  return (
    <>
      <PageHeader
        title="Diagnóstico"
        description="Capturas de error y, con «Guardar capturas, HTML y JSON» activado en Ajustes, lo necesario para calibrar cada web. Se borran solos a los 7 días."
      />
      <Card>
        {files.data.length ? (
          <TableWrap label="Archivos de diagnóstico">
            <table className={tableClass}>
              <thead>
                <tr><th scope="col">Archivo</th><th scope="col">Fecha</th><th scope="col" className="text-right!">KB</th></tr>
              </thead>
              <tbody>
                {files.data.map((f) => (
                  <tr key={f.name}>
                    <td>
                      <a href={`${API}/debug/files/${encodeURIComponent(f.name)}`} target="_blank" rel="noopener noreferrer"
                        className="inline-flex items-center gap-1.5 break-all text-accent hover:underline">
                        {f.image ? <Image className="size-4 shrink-0" aria-hidden="true" /> : <FileText className="size-4 shrink-0" aria-hidden="true" />}
                        {f.name}
                      </a>
                    </td>
                    <td className="whitespace-nowrap text-muted">{fmtDateTime(f.mtime)}</td>
                    <td className="text-right tabular-nums">{f.size_kb}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        ) : <p className="text-sm text-muted">No hay archivos de diagnóstico.</p>}
      </Card>
    </>
  )
}
