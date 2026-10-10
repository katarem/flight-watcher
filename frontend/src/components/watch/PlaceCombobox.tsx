import { Building2, Globe2, MapPin, Plane } from 'lucide-react'
import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'
import { usePlaces } from '@/api/queries'
import type { Place } from '@/api/types'
import { Badge } from '@/components/ui/card'
import { Spinner } from '@/components/ui/feedback'
import { cn } from '@/lib/cn'

const KIND_ICON = { airport: Plane, city: Building2, country: Globe2, group: MapPin }

/** Código tal como lo guarda el servidor: IATA/ISO en mayúsculas, grupos (palabras) en minúsculas. */
export const cleanCode = (text: string) => {
  const t = text.trim()
  return t.length <= 3 ? t.toUpperCase() : t.toLowerCase()
}

function useDebounced<T>(value: T, ms = 150): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

/** Origen o destino con autocompletado: aeropuertos, ciudades, países y grupos.
 *  `onChange` recibe el código y el lugar elegido de la lista (o null si solo se ha escrito).
 *  El texto inicial sale de `place`/`code`: para cambiarlo desde fuera, vuelve a montarlo con otra `key`. */
export function PlaceCombobox({ label, place, code, onChange, placeholder }: {
  label: string
  place: Place | null
  code: string
  onChange: (code: string, place: Place | null) => void
  placeholder?: string
}) {
  const id = useId()
  const listId = `${id}-lista`
  const hintId = `${id}-ayuda`
  const [text, setText] = useState(place?.label ?? code)
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const query = useDebounced(open ? text : '')
  const results = usePlaces(query)
  const options = open && query ? (results.data ?? []) : []
  const inputRef = useRef<HTMLInputElement>(null)

  const choose = (p: Place) => {
    onChange(p.code, p)
    setText(p.label)
    setOpen(false)
  }

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      if (!open) return setOpen(true)
      if (options.length) setActive((i) => (i + (e.key === 'ArrowDown' ? 1 : options.length - 1)) % options.length)
    } else if (e.key === 'Enter' && open && options[active]) {
      e.preventDefault()
      choose(options[active])
    } else if (e.key === 'Escape' && open) {
      e.preventDefault()
      setOpen(false)
    }
  }

  // Al salir sin elegir: si lo escrito es justo el código de la primera opción (o solo hay una), se elige.
  const onBlur = () => {
    if (!open) return
    const first = options[0]
    if (first && (first.code.toLowerCase() === text.trim().toLowerCase() || options.length === 1)) choose(first)
    else setOpen(false)
  }

  const Icon = place ? KIND_ICON[place.kind] : null
  const expanded = open && options.length > 0

  return (
    <div className="relative min-w-0 flex-1 space-y-1.5">
      <label htmlFor={id} className="block text-sm font-medium">{label}</label>
      <div className="relative">
        <input
          ref={inputRef}
          id={id}
          role="combobox"
          aria-expanded={expanded}
          aria-controls={expanded ? listId : undefined}
          aria-activedescendant={expanded && options[active] ? `${listId}-${active}` : undefined}
          aria-autocomplete="list"
          aria-describedby={hintId}
          autoComplete="off"
          spellCheck={false}
          value={text}
          placeholder={placeholder}
          onChange={(e) => {
            setText(e.target.value)
            setOpen(true)
            setActive(0)
            onChange(cleanCode(e.target.value), null)
          }}
          onFocus={(e) => e.target.select()}
          onKeyDown={onKey}
          onBlur={onBlur}
          className="h-10 w-full rounded-xl border border-line bg-surface px-3 pr-9 text-sm text-fg shadow-sm transition placeholder:text-muted/70 hover:border-muted/50 focus:border-accent focus:ring-3 focus:ring-accent/20 focus:outline-none"
        />
        <span className="pointer-events-none absolute inset-y-0 right-3 grid place-items-center text-muted [&_svg]:size-4">
          {open && results.isFetching ? <Spinner /> : Icon ? <Icon aria-hidden="true" /> : null}
        </span>
        {expanded && (
          <ul
            id={listId}
            role="listbox"
            aria-label={`Sugerencias para ${label.toLowerCase()}`}
            className="absolute inset-x-0 top-full z-30 mt-1 max-h-80 overflow-auto rounded-xl border border-line bg-surface p-1 shadow-xl"
          >
            {options.map((p, i) => {
              const KindIcon = KIND_ICON[p.kind]
              return (
                <li
                  key={p.code}
                  id={`${listId}-${i}`}
                  role="option"
                  aria-selected={i === active}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => choose(p)}
                  onMouseEnter={() => setActive(i)}
                  className={cn('flex cursor-pointer items-start gap-2.5 rounded-lg px-2.5 py-2', i === active && 'bg-surface-2')}
                >
                  <KindIcon className="mt-0.5 size-4 shrink-0 text-muted" aria-hidden="true" />
                  <span className="min-w-0 flex-1">
                    <span className="flex flex-wrap items-center gap-1.5 text-sm font-medium">
                      {p.label}
                      {p.kind !== 'airport' && <Badge tone="accent">{p.kind_label}</Badge>}
                    </span>
                    <span className="block truncate text-xs text-muted">{p.detail}</span>
                  </span>
                </li>
              )
            })}
          </ul>
        )}
      </div>
      <p id={hintId} className="text-xs text-muted">
        {place ? `${place.kind_label}: ${place.detail}` : 'Aeropuerto, ciudad, país o grupo (p. ej. Sevilla, TCI, Canarias).'}
      </p>
    </div>
  )
}
