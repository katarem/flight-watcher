import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'
import { errorList, put } from '@/api/client'
import { keys, useSettings } from '@/api/queries'
import type { SettingsData } from '@/api/types'
import { Button } from '@/components/ui/button'
import { PageHeader } from '@/components/ui/card'
import { ErrorBox, LoadError, PageLoading } from '@/components/ui/feedback'
import { Field, FormSection, Input, Switch } from '@/components/ui/form'
import { useTitle } from '@/lib/hooks'

function SettingsForm({ data }: { data: SettingsData }) {
  const qc = useQueryClient()
  const [v, setV] = useState<Record<string, string>>(data.values)
  const [errors, setErrors] = useState<string[]>([])
  const set = (k: string, value: string) => setV((s) => ({ ...s, [k]: value }))
  const save = useMutation({
    mutationFn: () => put<SettingsData>('/settings', v),
    onSuccess: (fresh) => {
      qc.setQueryData(keys.settings, fresh)
      qc.invalidateQueries({ queryKey: keys.status })
      toast.success('Ajustes guardados')
    },
    onError: (e) => {
      setErrors(errorList(e))
      window.scrollTo({ top: 0, behavior: 'smooth' })
    },
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    setErrors([])
    save.mutate()
  }
  const text = (k: string, label: string, opts: { hint?: string; placeholder?: string; numeric?: boolean } = {}) => (
    <Field label={label} hint={opts.hint}>
      {(id, hint) => <Input id={id} aria-describedby={hint} value={v[k] ?? ''} placeholder={opts.placeholder}
        inputMode={opts.numeric ? 'numeric' : undefined} onChange={(e) => set(k, e.target.value)} />}
    </Field>
  )

  return (
    <form onSubmit={submit} className="space-y-5" noValidate>
      <ErrorBox errors={errors} />
      <FormSection title="Panel">
        {text('panel_url', 'URL pública de este panel (opcional)', {
          placeholder: 'https://vuelos.midominio.com',
          hint: 'Si la rellenas, cada aviso incluye un enlace al historial y las gráficas de la vigilancia.',
        })}
        <p className="text-xs text-muted">
          Los canales de aviso (Discord, Telegram) los configura cada usuario en su{' '}
          <Link to="/profile" className="text-accent underline underline-offset-2">perfil</Link>.
        </p>
      </FormSection>

      <FormSection title="Programación" description="Cuándo se comprueban solas todas las vigilancias activas.">
        <div className="grid gap-4 sm:grid-cols-3">
          {text('schedule_hours', 'Horas (0-23, separadas por comas)', { placeholder: '8 o 8,20' })}
          {text('schedule_minute', 'Minuto', { numeric: true })}
          {text('timezone', 'Zona horaria', { placeholder: 'Europe/Madrid' })}
        </div>
        <div className="grid gap-4 sm:grid-cols-3">
          {text('max_months', 'Meses a recorrer del calendario', { numeric: true })}
          {text('min_samples', 'Muestras mínimas para «lo habitual»', { numeric: true })}
          {text('retention_days', 'Conservar histórico (días)', { numeric: true })}
        </div>
      </FormSection>

      <FormSection
        title="Enlaces por fecha"
        description="Marcadores: {origin} {destination} {date} (AAAA-MM-DD) {date_dmy} {year} {month} {day}. Vacío = el enlace por defecto."
      >
        {data.providers.map((p) => (
          <Field key={p.key} label={`Plantilla de enlace de ${p.label}`}>
            {(id) => <Input id={id} value={v[`link_${p.key}`] ?? ''} placeholder={p.default_link_template}
              onChange={(e) => set(`link_${p.key}`, e.target.value)} className="font-mono text-xs" spellCheck={false} />}
          </Field>
        ))}
      </FormSection>

      <FormSection title="Navegador y diagnóstico">
        <Switch checked={v.headless === '1'} onChange={(on) => set('headless', on ? '1' : '0')} label="Modo sin ventana (headless)"
          description="Solo afecta a las webs que se consultan con navegador." />
        <Switch checked={v.debug === '1'} onChange={(on) => set('debug', on ? '1' : '0')}
          label="Guardar capturas, HTML y JSON de cada comprobación"
          description={<>Se ven en <Link to="/debug" className="text-accent underline underline-offset-2">Diagnóstico</Link>.</>} />
        {text('proxy_url', 'Proxy (opcional)', { placeholder: 'http://usuario:clave@host:puerto' })}
      </FormSection>

      <Button type="submit" loading={save.isPending}>Guardar ajustes</Button>
    </form>
  )
}

export function SettingsPage() {
  useTitle('Ajustes')
  const settings = useSettings()
  if (settings.isPending) return <PageLoading />
  if (settings.isError) return <LoadError error={settings.error} />
  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader title="Ajustes" description="Globales para todo el panel. Solo los ven los administradores." />
      <SettingsForm data={settings.data} />
    </div>
  )
}
