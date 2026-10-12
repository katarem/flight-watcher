import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ChevronLeft, FileUp, Link2, ShieldAlert, Upload } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'
import { toast } from 'sonner'
import { errorList, post } from '@/api/client'
import { keys, useProvidersAdmin } from '@/api/queries'
import type { ImportItem, ImportPreview } from '@/api/types'
import { Button, buttonClass } from '@/components/ui/button'
import { Badge, Card, CardHeader, PageHeader } from '@/components/ui/card'
import { ErrorBox, LoadError, PageLoading } from '@/components/ui/feedback'
import { Checkbox, Field, Input, Switch } from '@/components/ui/form'
import { useTitle } from '@/lib/hooks'

/** Nombre en castellano de cada dato de un proveedor (para decir qué cambia al importarlo). */
const FIELD_LABELS: Record<string, string> = {
  label: 'nombre', color: 'color', coverage: 'cobertura', max_routes: 'máximo de pares', health_origin: 'ruta de prueba',
  health_destination: 'ruta de prueba', link_template: 'plantilla de enlace', notes: 'notas', min_interval: 'pausa',
  stealth: 'medidas anti-bot', code: 'código',
}

function StatusTag({ item }: { item: ImportItem }) {
  if (item.errors.length) return <Badge tone="danger">No se puede importar</Badge>
  if (item.status === 'new') return <Badge tone="accent">Nuevo</Badge>
  if (item.status === 'same') return <Badge>Igual que el guardado</Badge>
  const changed = [...new Set(item.changes.map((c) => FIELD_LABELS[c] ?? c))]
  return <Badge tone="warn">Sustituye al guardado: cambia {changed.join(', ')}</Badge>
}

function PreviewItem({ item, checked, onChange }: { item: ImportItem; checked: boolean; onChange: (v: boolean) => void }) {
  const bad = item.errors.length > 0
  return (
    <li className="space-y-2 py-3 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-center gap-2">
        <Checkbox checked={checked} onChange={onChange} disabled={bad}>
          <span aria-hidden="true" className="size-3 rounded-full" style={{ background: item.color }} />
          <span className="font-medium">{item.label}</span>
          <span className="font-mono text-xs text-muted">{item.key}</span>
        </Checkbox>
        <StatusTag item={item} />
      </div>
      <p className="text-xs text-muted">
        Cobertura: {item.coverage_label}
        {item.status !== 'new' && ` · lo usan ${item.n_watches} ${item.n_watches === 1 ? 'vigilancia' : 'vigilancias'}`}
      </p>
      {item.notes && <p className="text-sm text-muted">{item.notes}</p>}
      {bad && <ErrorBox errors={item.errors} />}
      <details className="rounded-xl border border-line">
        <summary className="cursor-pointer px-3 py-2 text-sm font-medium">Ver el código ({item.code.split('\n').length} líneas)</summary>
        <pre className="max-h-96 overflow-auto border-t border-line bg-surface-2 p-3 text-xs leading-5" tabIndex={0}
          aria-label={`Código de ${item.label}`}>{item.code}</pre>
      </details>
    </li>
  )
}

export function ProviderImportPage() {
  useTitle('Importar proveedores')
  const list = useProvidersAdmin()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [url, setUrl] = useState('')
  const [file, setFile] = useState<{ name: string; text: string } | null>(null)
  const [preview, setPreview] = useState<ImportPreview | null>(null)
  const [chosen, setChosen] = useState<Set<string>>(new Set())
  const [enabled, setEnabled] = useState(true)
  const [password, setPassword] = useState('')
  const [errors, setErrors] = useState<string[]>([])
  const [importErrors, setImportErrors] = useState<string[]>([])

  const read = useMutation({
    mutationFn: (body: { url?: string; text?: string }) => post<ImportPreview>('/providers/import/preview', body),
    onMutate: () => {
      setErrors([])
      setImportErrors([])
      setPreview(null)
    },
    onSuccess: (res) => {
      setPreview(res)
      setChosen(new Set(res.providers.filter((p) => !p.errors.length && p.status !== 'same').map((p) => p.key)))
    },
    onError: (e) => setErrors(errorList(e)),
  })

  const apply = useMutation({
    mutationFn: () => post<{ imported: string[]; created: string[] }>('/providers/import', {
      text: preview!.text, url: preview!.source ?? '', keys: [...chosen], enabled, password,
    }),
    onMutate: () => setImportErrors([]),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: keys.providers })
      qc.invalidateQueries({ queryKey: keys.meta })
      const n = res.imported.length
      toast.success(`${n} ${n === 1 ? 'proveedor importado' : 'proveedores importados'}`, {
        description: res.created.length < n ? 'Los que ya existían se han sustituido.' : undefined,
      })
      navigate('/admin/providers')
    },
    onError: (e) => setImportErrors(errorList(e)),
  })

  if (list.isPending) return <PageLoading />
  if (list.isError) return <LoadError error={list.error} />

  const suggestions = [
    ...list.data.catalogs,
    ...list.data.sources.filter((s) => !list.data.catalogs.some((c) => c.url === s)).map((s) => ({ label: s, url: s })),
  ]
  const fromUrl = (e: FormEvent) => {
    e.preventDefault()
    setFile(null)
    read.mutate({ url })
  }
  const pickFile = async (f: File | undefined) => {
    if (!f) return
    const text = await f.text()
    setFile({ name: f.name, text })
    setUrl('')
    read.mutate({ text })
  }
  const toggle = (key: string, on: boolean) => setChosen((s) => {
    const next = new Set(s)
    if (on) next.add(key)
    else next.delete(key)
    return next
  })

  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader
        back={<Link to="/admin/providers" className="inline-flex items-center gap-1 text-sm text-muted hover:text-fg"><ChevronLeft className="size-4" aria-hidden="true" /> Proveedores</Link>}
        title="Importar proveedores"
        description="Desde un enlace (por ejemplo, un archivo .fwp en GitHub) o desde un archivo exportado de otro panel. Antes de importar verás qué trae cada proveedor y su código."
      />
      {!list.data.editable ? (
        <p className="rounded-xl border border-warn/30 bg-warn/10 p-3 text-sm text-warn">
          En este servidor no se pueden importar proveedores desde el panel (<code>PROVIDER_SCRIPTS=0</code>).
        </p>
      ) : (
        <div className="space-y-4">
          <Card aria-labelledby="import-origen">
            <CardHeader id="import-origen" title="¿De dónde?" />
            <div className="space-y-4">
              <ErrorBox errors={errors} />
              <form onSubmit={fromUrl} className="flex flex-wrap items-end gap-3" noValidate>
                <Field label="Enlace del paquete" className="min-w-0 flex-1 basis-72"
                  hint="Un enlace de GitHub a un archivo (…/blob/…) se cambia solo por el del archivo en bruto.">
                  {(id, hint) => <Input id={id} aria-describedby={hint} type="url" value={url} spellCheck={false}
                    placeholder="https://raw.githubusercontent.com/…/proveedores.fwp" onChange={(e) => setUrl(e.target.value)} />}
                </Field>
                <Button type="submit" variant="secondary" loading={read.isPending && !file} disabled={!url.trim() || read.isPending}>
                  {!(read.isPending && !file) && <Link2 />} Leer el enlace
                </Button>
              </form>
              {suggestions.length > 0 && (
                <div className="space-y-1.5">
                  <p className="text-xs text-muted">Enlaces conocidos:</p>
                  <ul className="flex flex-wrap gap-2">
                    {suggestions.map((s) => (
                      <li key={s.url} className="min-w-0 max-w-full">
                        <Button type="button" size="sm" variant="ghost" className="max-w-full" title={s.url}
                          onClick={() => {
                            setUrl(s.url)
                            setFile(null)
                            read.mutate({ url: s.url })
                          }}>
                          <span className="truncate">{s.label}</span>
                        </Button>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              <div className="border-t border-line pt-4">
                <Field label="O un archivo exportado (.fwp)">
                  {(id) => (
                    <div className="flex flex-wrap items-center gap-3">
                      <input id={id} type="file" accept=".fwp,.txt,text/plain" className="peer sr-only"
                        onChange={(e) => {
                          void pickFile(e.target.files?.[0])
                          e.target.value = ''
                        }} />
                      <label htmlFor={id} aria-hidden="true"
                        className={buttonClass('secondary', 'sm', 'cursor-pointer peer-focus-visible:outline-2 peer-focus-visible:outline-(--fw-ring)')}>
                        <FileUp /> Elegir archivo
                      </label>
                      {file && <span className="text-sm text-muted">{file.name}</span>}
                    </div>
                  )}
                </Field>
              </div>
            </div>
          </Card>

          {preview && (
            <Card aria-labelledby="import-contenido">
              <CardHeader id="import-contenido" title={`Qué trae (${preview.providers.length})`}
                description={preview.source ? `Leído de ${preview.source}` : `Leído del archivo ${file?.name ?? ''}`} />
              <ul className="divide-y divide-line">
                {preview.providers.map((item) => (
                  <PreviewItem key={item.key} item={item} checked={chosen.has(item.key)} onChange={(on) => toggle(item.key, on)} />
                ))}
              </ul>
            </Card>
          )}

          {preview && (
            <section aria-labelledby="import-confirmar" className="space-y-3 rounded-2xl border border-warn/40 bg-warn/8 p-4 sm:p-5">
              <h2 id="import-confirmar" className="flex items-center gap-2 text-base font-semibold">
                <ShieldAlert className="size-5 text-warn" aria-hidden="true" /> Importar
              </h2>
              <p className="text-sm">
                Los scripts se ejecutan en el servidor con todos sus permisos: importa solo paquetes de quien te fíes y
                revisa su código. Un proveedor con la misma clave que uno guardado lo sustituye (sus vigilancias y su
                histórico se conservan).
              </p>
              <ErrorBox errors={importErrors} />
              <Switch checked={enabled} onChange={setEnabled} label="Dejarlos activos"
                description="Activos, se pueden elegir en las vigilancias en cuanto se importan." />
              <Field label="Tu contraseña" className="max-w-sm">
                {(id) => <Input id={id} type="password" autoComplete="current-password" value={password}
                  onChange={(e) => setPassword(e.target.value)} />}
              </Field>
              <Button type="button" onClick={() => apply.mutate()} loading={apply.isPending} disabled={!chosen.size}>
                {!apply.isPending && <Upload />} {chosen.size === 1 ? 'Importar 1 proveedor' : `Importar ${chosen.size} proveedores`}
              </Button>
            </section>
          )}
        </div>
      )}
    </div>
  )
}
