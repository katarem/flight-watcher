/** Formateo de fechas y precios (el mismo criterio que `app/fmt.py`, que usan los avisos). */

const DIAS = ['lun', 'mar', 'mié', 'jue', 'vie', 'sáb', 'dom']
export const MESES = [
  'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
  'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre',
]

const pad = (n: number) => String(n).padStart(2, '0')

/** Fecha local a partir de 'AAAA-MM-DD' (sin desfases de zona horaria). */
export function parseDay(iso: string): Date {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number)
  return new Date(y, m - 1, d)
}

export function isoDay(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** «lun 12/10/2026» */
export function fmtDay(iso: string): string {
  const d = parseDay(iso)
  return `${DIAS[(d.getDay() + 6) % 7]} ${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()}`
}

/** «12/10/26», para ejes de gráficas. */
export function fmtShortDay(iso: string): string {
  return `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(2, 4)}`
}

/** «30 €» o «30,50 €». */
export function fmtPrice(value: number | null | undefined): string {
  if (value == null) return '—'
  if (Math.abs(value - Math.round(value)) < 0.005) return `${Math.round(value)} €`
  return `${value.toFixed(2).replace('.', ',')} €`
}

/** Precio redondeado al euro, para huecos estrechos (calendario). */
export function fmtPriceShort(value: number | null | undefined): string {
  return value == null ? '—' : `${Math.round(value)} €`
}

/** «12/10/2026 08:00» a partir de un ISO con hora (con o sin zona). */
export function fmtDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const d = new Date(value.length === 19 ? value : value.replace(' ', 'T'))
  if (Number.isNaN(d.getTime())) return value
  return `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** «hace 5 min», «hace 3 h», «hace 2 días» (o la fecha si es antigua). */
export function fmtAgo(value: string | null | undefined, now: Date = new Date()): string {
  if (!value) return '—'
  const d = new Date(value)
  const mins = Math.round((now.getTime() - d.getTime()) / 60000)
  if (Number.isNaN(mins)) return value
  if (mins < 1) return 'ahora mismo'
  if (mins < 60) return `hace ${mins} min`
  const hours = Math.round(mins / 60)
  if (hours < 24) return `hace ${hours} h`
  const days = Math.round(hours / 24)
  if (days < 8) return `hace ${days} ${days === 1 ? 'día' : 'días'}`
  return fmtDateTime(value).slice(0, 10)
}
