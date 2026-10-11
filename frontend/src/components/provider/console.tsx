import { Check, ChevronRight, Copy, Globe, MessageSquareText, TriangleAlert, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import type { ConsoleEvent, ConsoleLevel } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/feedback'

/** Cómo se pinta cada nivel de la consola (icono, color del texto y etiqueta para lectores de pantalla). */
const LEVELS: Record<ConsoleLevel, { icon: typeof Check | null; className: string; sr: string }> = {
  step: { icon: ChevronRight, className: 'font-semibold text-fg', sr: 'Paso' },
  info: { icon: null, className: 'text-muted', sr: '' },
  ok: { icon: Check, className: 'text-deal', sr: 'Bien' },
  warn: { icon: TriangleAlert, className: 'text-warn', sr: 'Aviso' },
  error: { icon: X, className: 'text-danger', sr: 'Error' },
  http: { icon: Globe, className: 'text-accent', sr: 'Petición' },
  script: { icon: MessageSquareText, className: 'text-fg', sr: 'Mensaje del script' },
}

const stamp = (ms: number) => `+${(ms / 1000).toFixed(2)} s`

/**
 * Consola de la prueba de un proveedor: cada paso, cada petición (URL, estado, tiempo, tamaño y forma del JSON),
 * los `api.log`/`print` del script y la línea en la que falla, según van llegando. Se desplaza sola al final salvo
 * que el usuario haya subido para leer algo.
 */
export function ScriptConsole({ events, running, onClose }: {
  events: ConsoleEvent[]
  running: boolean
  onClose: () => void
}) {
  const box = useRef<HTMLDivElement>(null)
  const stick = useRef(true)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    const el = box.current
    if (el && stick.current) el.scrollTop = el.scrollHeight
  }, [events.length])

  const copy = async () => {
    const text = events.map((e) => `${stamp(e.t).padEnd(9)} ${e.level.padEnd(6)} ${e.text}`).join('\n')
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      toast.error('No se ha podido copiar la consola')
    }
  }

  return (
    <section aria-labelledby="consola" className="overflow-hidden rounded-xl border border-line bg-surface-2">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2">
        <h3 id="consola" className="flex items-center gap-2 text-sm font-semibold">
          Consola de la prueba
          {running ? (
            <span className="flex items-center gap-1.5 text-xs font-normal text-muted" role="status">
              <Spinner className="size-3.5" /> Ejecutando…
            </span>
          ) : (
            <span className="text-xs font-normal text-muted">{events.length} líneas</span>
          )}
        </h3>
        <div className="flex gap-1">
          <Button type="button" size="sm" variant="ghost" onClick={copy} disabled={!events.length}>
            {copied ? <Check /> : <Copy />} {copied ? 'Copiada' : 'Copiar'}
          </Button>
          <Button type="button" size="sm" variant="ghost" onClick={onClose} disabled={running} aria-label="Cerrar la consola">
            <X />
          </Button>
        </div>
      </div>
      <div
        ref={box}
        role="log"
        aria-label="Salida de la prueba"
        tabIndex={0}
        onScroll={(e) => {
          const el = e.currentTarget
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24
        }}
        className="max-h-80 min-h-24 overflow-auto px-3 py-2 font-mono text-xs leading-5"
      >
        {events.map((e, i) => {
          const lvl = LEVELS[e.level] ?? LEVELS.info
          const Icon = lvl.icon
          return (
            <div key={i} className={`flex gap-2 ${e.level === 'step' && i > 0 ? 'mt-2' : ''}`}>
              <span className="w-16 shrink-0 text-right text-muted tabular-nums">{stamp(e.t)}</span>
              <span className="flex w-3.5 shrink-0 justify-center pt-0.5" aria-hidden="true">
                {Icon && <Icon className={`size-3.5 ${lvl.className}`} />}
              </span>
              <span className={`min-w-0 break-all whitespace-pre-wrap ${lvl.className}`}>
                {lvl.sr && <span className="sr-only">{lvl.sr}: </span>}
                {e.text}
              </span>
            </div>
          )
        })}
        {running && !events.length && <p className="text-muted">Esperando al servidor…</p>}
      </div>
    </section>
  )
}
