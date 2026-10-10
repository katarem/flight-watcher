import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useProviders } from '@/api/queries'
import type { Series } from '@/api/types'
import { fmtDay, fmtPrice, fmtShortDay } from '@/lib/format'

/** Una línea por web (o por serie de `names`). `labels` son fechas ISO; los huecos (null) se unen. */
export function PriceChart({ data, height = 260, label, names }: {
  data: Series
  height?: number
  label: string
  /** Nombre y color de series que no son webs (p. ej. el total de un viaje). */
  names?: Record<string, { label: string; color: string }>
}) {
  const providers = useProviders()
  const provider = (k: string) => names?.[k] ?? providers(k)
  const keys = Object.keys(data.series)
  const rows = data.labels.map((l, i) => ({ l, ...Object.fromEntries(keys.map((k) => [k, data.series[k][i]])) }))
  const many = rows.length > 40
  if (!rows.length)
    return <p className="text-sm text-muted">Aún no hay datos suficientes. Pulsa «Comprobar ahora» y vuelve en unos minutos.</p>

  return (
    <figure aria-label={label} style={{ height }} className="-ml-2">
      <ResponsiveContainer>
        <LineChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="var(--fw-line)" strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="l" tickFormatter={fmtShortDay} tick={{ fontSize: 11, fill: 'var(--fw-muted)' }}
            stroke="var(--fw-line)" minTickGap={24} />
          <YAxis tickFormatter={(v: number) => `${v} €`} tick={{ fontSize: 11, fill: 'var(--fw-muted)' }}
            stroke="var(--fw-line)" width={56} domain={['auto', 'auto']} />
          <Tooltip
            labelFormatter={(l) => fmtDay(String(l))}
            formatter={(v, name) => [fmtPrice(Number(v)), provider(String(name)).label]}
            contentStyle={{ background: 'var(--fw-surface)', border: '1px solid var(--fw-line)', borderRadius: 12, fontSize: 13 }}
            labelStyle={{ color: 'var(--fw-fg)', fontWeight: 600 }}
            // El texto, en el color del tema: el de cada web no siempre da el contraste AA (la línea ya lo lleva).
            itemStyle={{ color: 'var(--fw-fg)' }}
          />
          {keys.length > 1 && <Legend formatter={(k) => provider(String(k)).label} wrapperStyle={{ fontSize: 12 }} />}
          {keys.map((k) => (
            <Line key={k} type="monotone" dataKey={k} stroke={provider(k).color} strokeWidth={2} connectNulls
              dot={many ? false : { r: 2.5 }} activeDot={{ r: 5 }} animationDuration={600} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </figure>
  )
}
